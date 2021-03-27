import os 
import logging 

from flask import Blueprint, request, url_for, current_app, session, g
try:
    from flask_restplus import Api, Namespace, Resource, fields
except ImportError:
    import werkzeug
    werkzeug.cached_property = werkzeug.utils.cached_property
    from flask_restplus import Api, Namespace, Resource, fields
from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash, check_password_hash
from flask_restplus import Api
from pymongo import MongoClient
from datetime import datetime 
from PIL import Image
import functools

from .config import policy, server_config

# database 
mongoClient = MongoClient('mongodb://localhost:27017/')
db = mongoClient['activity']

# https://github.com/noirbizarre/flask-restplus/issues/223
class Custom_API(Api):
    @property
    def specs_url(self):
        '''
        The Swagger specifications absolute url (ie. `swagger.json`)

        :rtype: str
        '''
        return url_for(self.endpoint('specs'), _external=False)

# blueprint 
bp = Blueprint('api', __name__, url_prefix='/api')
api = Custom_API(bp, version='1.0')

upload_parser = api.parser()
upload_parser.add_argument('media', location='files',
                           type=FileStorage, required=True)

signup = Namespace('signup')
login = Namespace('login')
logout = Namespace('logout')
events = Namespace('events')
monitoring = Namespace('monitoring')
screenshot = Namespace('screenshot')
policy_url = Namespace('policy')

api.add_namespace(login)
api.add_namespace(logout)
api.add_namespace(events)
api.add_namespace(signup)
api.add_namespace(monitoring)
api.add_namespace(screenshot)
api.add_namespace(policy_url)

signup_fields = {}
signup_fields['group'] = fields.String(required=True, description='group', help='group cannot be blank.')
signup_fields['name'] = fields.String(required=True, description='name', help='name cannot be blank.')
signup_fields['password'] = fields.String(required=True, description='password', help='password cannot be blank.')
signup_fields['email'] = fields.String(required=True, description='email', help='email cannot be blank.')

login_fields = {}
login_fields['email'] = fields.String(required=True, description='email', help='user_id cannot be blank.')
login_fields['password'] = fields.String(required=True, description='password', help='password cannot be blank.')
login_fields['computer_name'] = fields.String(required=False, description='computer_name', help='computer_name can be blank.')
login_fields['client_ver'] = fields.String(required=False, description='computer_name', help='client_ver can be blank.')

data_fields = {}
data_fields['event_id'] = fields.Integer(required=True, description='starttime', help='event_id cannot be blank.')
data_fields['start_time'] = fields.DateTime(required=True, description='starttime', help='start_time cannot be blank.')
data_fields['end_time'] = fields.DateTime(required=False, description='endtime', help='end_time can be blank.')
data_fields['is_active'] = fields.Boolean(required=True, description='isActive', help='is_acitve cannot be blank.')
data_fields['app'] = fields.String(required=True, description='app', help='timestamp cannot be blank.') 
data_fields['title'] = fields.String(required=True, description='title', help='title cannot be blank.')
data_fields['url'] = fields.String(required=False, description='url', help='url can be blank.')

data_model = api.model('data', data_fields)

events_fields = {}
events_fields['group'] = fields.String(required=True, description='group', help='group cannot be blank.')
events_fields['user_id'] = fields.String(required=True, description='user_id', help='user_id cannot be blank.')
events_fields['data'] = fields.List(fields.Nested(data_model))

monitoring_fields = {}
monitoring_fields['group'] = fields.String(required=True, description='group', help='group cannot be blank.')

screenshot_fields = {}
screenshot_fields['group'] = fields.String(required=True, description='group', help='group cannot be blank.')
screenshot_fields['user_id'] = fields.String(required=True, description='user_id', help='user_id cannot be blank.')

signup_model = api.model('signup', signup_fields)
login_model = api.model('login', login_fields)
events_model = api.model('events', events_fields)
monitoring_model = api.model('group', monitoring_fields)
screenshot_model = api.model('screenshot', screenshot_fields)

def login_required(view):
    @functools.wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            return 'login required', 400
        return view(*args, **kwargs)
    return wrapped_view

@signup.route('/')
class signup(Resource):
    @api.doc(responses={200: 'OK', 400: 'Invalid Argument', 500: 'Mapping Key Error'})
    @api.expect(signup_model)
    def post(self):
        request_data = request.json 
        collection = db['users']
        user_data = collection.find_one(filter={'email': request_data['email']})
        if user_data:
            return '', 400
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
            request_data['password'] = generate_password_hash(request_data['password'])
            request_data['create_time'] = str(datetime.now())
            request_data['user_id'] = user_id
            collection.insert(request_data)
            return '', 200

@login.route('/')
class Login(Resource):
    @api.doc(responses={200: 'OK', 400: 'Invalid Argument', 500: 'Mapping Key Error'})
    @api.expect(login_model)
    def post(self):
        request_data = request.json
        email = request_data['email']
        password = generate_password_hash(request_data['password'])

        computer_name = None 
        if 'computer_name' in request_data:
            computer_name = request_data['computer_name'] 
        collection = db['users']
        user_data = collection.find_one(filter={'email': email})
        if user_data:
            if not check_password_hash(user_data['password'], request_data['password']):
                return 'wrong password', 400
            group = user_data['group']
            user_id = user_data['user_id']
            del user_data['_id']
            del user_data['password'] 

            collection = db['clients']
            client_data = collection.find_one(filter={'user_id':user_id, 'group':group})
            if computer_name:
                if client_data:
                    if client_data['computer_name'] != computer_name:
                        return 'wrong computer_name', 400
                else:
                    new_client = {'group':group, 'user_id':user_id, 'computer_name':computer_name, 'create_time': str(datetime.now())}
                    collection.insert_one(new_client)
            else:
                session.clear()
                for key in user_data:
                    session[key] = user_data[key]
                return {'group': group, 'user_id': user_id}, 200
            collection = db['events']
            event_data = collection.find_one(filter={'user_id':user_id}, sort=[('start_time', -1)])
            if event_data:
                event_id = event_data['event_id']
            else:
                event_id = 0
            data = {'group':group, 'user_id':user_id, 'event_id':event_id, 'policy':policy}
            session.clear()
            for key in user_data:
                session[key] = user_data[key]
            return data, 200
        else:
            return 'wrong email', 400

@logout.route('/')
class Logout(Resource):
    @login_required
    def get(self):
        session.clear()
        return '', 200

@events.route('/')
class Events(Resource):
    def get(self):
        return 'hello'
    
    @login_required
    @api.doc(responses={200: 'OK', 400: 'Invalid Argument', 500: 'Mapping Key Error'},)
    @api.expect(events_model)
    def post(self):
        if 'X-Real_Ip' in request.headers:
            current_app.logger.info('remote: %s' % request.headers['X-Real-Ip'])
        request_data = request.json
        collection = db['events'] 
        len_data = len(request_data['data'])
        for i in range(len_data):
            update = {}
            update = request_data['data'][i]
            update['user_id'] = request_data['user_id']
            collection.update_one(
                    filter={'user_id': update['user_id'], 'event_id': update['event_id']}, 
                    update={'$set':update}, upsert=True)
        return '', 200

@monitoring.route('/')
class Monitoring(Resource):
    @api.doc(responses={200: 'OK', 400: 'Invalid Argument', 500: 'Mapping Key Error'},)
    @api.expect(monitoring_model)
    def post(self):
        request_data = request.json
        collection = db['users']
        ids = collection.find( filter={'group': request_data['group']})
        collection = db['events']
        data_list = []
        for id in ids:
            user_id = id['user_id']
            event_data = collection.find_one(
                filter={'user_id': user_id},
                sort=[('start_time', -1)])
            event_data['name'] = id['name']
            del event_data['_id']
            data_list.append(event_data) 
        return data_list, 200

# multipc를 사용하는 경우는 어떻게?? 
@screenshot.route('/')
class Screenshot(Resource):
    @login_required
    @api.doc(responses={200: 'OK', 400: 'Invalid Argument', 500: 'Mapping Key Error'})
    @api.expect(upload_parser)
    def post(self):
        if 'X-Real_Ip' in request.headers:
            current_app.logger.info('remote: %s' %request.headers['X-Real-Ip'])
        args = upload_parser.parse_args() # upload a file
        upload = args['media']
        img = Image.open(upload)
        save_dir = os.path.join(os.getcwd(), 'static', server_config['base_img_dir'], g.user['group'], str(g.user['user_id']), upload.filename.split(' ')[0])
        if os.path.exists(save_dir):
            pass
        else:
            os.makedirs(save_dir)
        img.save(save_dir + '/' + upload.filename)
        data = {'save_dir': save_dir}
        return data, 200

@policy_url.route('/')
class Policy(Resource):
    def get(self):
        return policy, 200