import os

from flask import Blueprint, request, render_template, url_for, current_app, session, g, flash, send_file, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import redirect
from pymongo import MongoClient
from datetime import datetime
from PIL import Image 
import functools

from .config import server_config
from forms import UserCreateForm, UserLoginForm

#check os
os_name = os.name

# database 
mongoClient = MongoClient('mongodb://localhost:27017/')
db = mongoClient['activity']

def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for('main.login'))
        return view(**kwargs)
    return wrapped_view

bp = Blueprint('main', __name__, url_prefix='/')
@bp.route('/')
def index():
    return render_template('/base.html')

# 사용자 전체를 보는 것으로 설정
# group 별 권한 별로 보는 것 설정 필요 
@bp.route('/monitoring/', methods=['GET', 'POST'])
@login_required
def monitoring():
    if 'X-Real-IP' in request.headers: # when using proxy-pass like nginx
        current_app.logger.info('remote: %s' %request.headers['X-Real-Ip'])
    if request.method == 'POST':
        data = request.json
    else:
        data = {'group':'activity'}
    collection = db['users']
    group = data['group']
    # ids = collection.find(filter={'group': group})
    ids = collection.find()
    collection = db['events']
    ids_list = []
    img_list = []
    data_dict = {}
    if ids:
        for id in ids:
            group = id['group']
            user_id = id['user_id'] 
            event_data = collection.find_one(
                filter={'user_id': user_id},
                sort=[('start_time', -1)])
            user_id = str(user_id)  # path 설정을 위해 str 변환 필요 
            if event_data:
                event_data['group'] = id['group']
                event_data['name'] = id['name']
                event_data['start_time'] = event_data['start_time'].split('.')[0]
                del event_data['_id']
                img_dir = os.path.join(os.getcwd(), 'static', server_config['base_img_dir'], group, user_id)
                if os_name == 'nt':
                    rel_dir = server_config['base_img_dir'] + '/' + group + '/' + user_id
                else:
                    rel_dir = os.path.join(server_config['base_img_dir'], group, user_id)
                try:
                    sub_dir = os.listdir(img_dir)
                except Exception as e:
                    print(e)
                else:
                    if sub_dir:
                        img_dir = os.path.join(img_dir, max(sub_dir))
                        if os_name == 'nt':
                            rel_dir = rel_dir + '/' + max(sub_dir)
                        else:
                            rel_dir = os.path.join(rel_dir, max(sub_dir))
                        file_name = max(os.listdir(img_dir))
                    else:
                        file_name = None
                    if file_name:
                        img_path = os.path.join(img_dir, file_name)
                        if os_name == 'nt':
                            rel_path = rel_dir + '/' + file_name
                        else:
                            rel_path = os.path.join(rel_dir, file_name)
                        img = Image.open(img_path)
                        width, height = img.size
                        img_size = {'width':int(width/height * server_config['screenshot_img_height']), 'height':server_config['screenshot_img_height']}
                    else:
                        rel_path = file_name 
                        img_size = None 
                    img_data = {'name':id['name'], 'path':rel_path, 'size':img_size}
                    ids_list.append(event_data) 
                    img_list.append(img_data)
    data_dict['ids'] = ids_list
    data_dict['imgs'] = img_list
    return render_template('/monitoring.html', data_dict=data_dict)

@bp.route('/signup/', methods=('GET', 'POST'))
def signup():
    form = UserCreateForm()
    if request.method == 'POST' and form.validate_on_submit():
        request_data = {'group': form.group.data,  'name': form.name.data, 'email': form.email.data, 'password': generate_password_hash(form.password1.data)} 
        collection = db['users']
        user_data = collection.find_one(filter={'email': request_data['email']})
        if user_data:
            flash('이미 존재하는 사용자입니다.')
        else:
            user_data = collection.find_one(filter={'group': request_data['group']})
            request_data['admin'] = False
            if user_data is None:
                request_data['admin'] = True
            user_data = collection.find_one(sort=[('create_time', -1)])
            if user_data:
                user_id = user_data['user_id'] + 1
            else:
                user_id = 1
            request_data['create_time'] = str(datetime.now())
            request_data['user_id'] = user_id
            collection.insert(request_data)
            return redirect(url_for('main.index'))
    return render_template('/signup.html', form=form)

@bp.route('/login/', methods=('GET', 'POST'))
def login():
    form = UserLoginForm()
    if request.method == 'POST' and form.validate_on_submit():
        error = None
        request_data = {'email': form.email.data, 'password': form.password.data} 
        collection = db['users']
        user_data = collection.find_one(filter={'email': request_data['email']})
        if not user_data:
            error = "존재하지 않는 사용자입니다."
        elif not check_password_hash(user_data['password'], request_data['password']):
            error = "비밀번호가 올바르지 않습니다."
        if error is None:
            del user_data['_id']
            del user_data['password'] 

            session.clear()
            for key in user_data:
                session[key] = user_data[key] 
            return redirect(url_for('main.index'))
        flash(error)
    return render_template('/login.html', form=form)

@bp.route('/logout/')
@login_required
def logout():
    session.clear()
    return redirect(url_for('main.index'))

@bp.route('/download/<path:filename>')
@login_required
def download(filename):
    if os.path.exists('downloads'):
        files = os.listdir('./downloads')
    else:
        os.makedirs('downloads')
        files = os.listdir('./downloads')
    path = './downloads/'
    if filename in files:
        return send_file(path + filename, attachment_filename=filename, as_attachment=True)
    elif files:
        return send_file(path + files[0], attachment_filename=filename, as_attachment=True)
    else:
        return redirect(url_for('main.index'))

@bp.before_app_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        g.user = {}
        for key in session:
            g.user[key] = session[key]



