import os, sys
import logging
import logging.handlers
from typing import Optional

from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton, QLabel, QLineEdit, QGridLayout, QMessageBox)
from PyQt5.QtTest import QTest

import win32gui
import win32process
import uiautomation as auto
import wmi

import ctypes
from ctypes import Structure, POINTER, WINFUNCTYPE, windll  # type: ignore
from ctypes.wintypes import BOOL, UINT, DWORD  # type: ignore

import requests
import json
from PIL import ImageGrab
from datetime import datetime

from config import config

c = wmi.WMI()

client_ver = config['client_ver']

session = requests.session()

class LoginForm(QWidget):
    def __init__(self):
        super().__init__()

        self.user_data = None

        self.setWindowTitle('Login Form')
        self.resize(500, 120)

        layout = QGridLayout()

        label_url = QLabel('<font size="4"> url </font>')
        self.lineEdit_url = QLineEdit()
        self.lineEdit_url.setPlaceholderText('Please enter your server url')
        layout.addWidget(label_url, 0, 0)
        layout.addWidget(self.lineEdit_url, 0, 1)

        label_email = QLabel('<font size="4"> Email </font>')
        self.lineEdit_email = QLineEdit()
        self.lineEdit_email.setPlaceholderText('Please enter your email')
        layout.addWidget(label_email, 1, 0)
        layout.addWidget(self.lineEdit_email, 1, 1)

        label_password = QLabel('<font size="4"> Password </font>')
        self.lineEdit_password = QLineEdit()
        self.lineEdit_password.setPlaceholderText('Please enter your password')
        layout.addWidget(label_password, 2, 0)
        layout.addWidget(self.lineEdit_password, 2, 1)

        button_login = QPushButton('Login')
        button_login.clicked.connect(self.check_login)
        layout.addWidget(button_login, 3, 0, 2, 2)
        layout.setRowMinimumHeight(3, 75)

        self.setLayout(layout)

    def check_login(self):
        msg = QMessageBox()

        # login
        base_url = self.lineEdit_url.text()

        self.urls = {'login':base_url + '/api/login/',
                'events':base_url + '/api/events/',
                'capture':base_url + '/api/capture/',
                'screenshot':base_url + '/api/screenshot/'}
        self.email = self.lineEdit_email.text()
        self.password = self.lineEdit_password.text()
        status_code, data = self.login_request()

        if status_code == 200:
            msg.setText('Success')
            self.lineEdit_email.setText('')
            self.lineEdit_password.setText('')
            # msg.exec_()
            form.close()
            self.activity()
        else:
            msg.setText(data)
            msg.exec_()

    def login_request(self):
        logger.info('login_request')
        computer_name = os.environ['COMPUTERNAME']
        status_code, data = _request_data('POST', self.urls['login'],
                                data={'email':self.email, 'password':self.password,
                                      'computer_name':computer_name, 'client_ver':client_ver})
        if status_code == 200:
            logger.info('connected')
            self.user_data = json.loads(data)
            self.group = self.user_data['group']
            self.user_id = self.user_data['user_id']
            self.event_id = self.user_data['event_id']
            self.policy = self.user_data['policy']
        return status_code, data

    def activity(self):

        self.sent_timestamp = datetime.now()
        self.capture_timestamp = datetime.now()
        window = ''
        self.is_new = True

        # data
        data = {'user_id':self.user_id, 'data': []}
        while True:
            self.current_timestamp = datetime.now()
            hwnd = get_active_window_handle()
            seconds_since_input = seconds_since_last_input()
            if seconds_since_input > self.policy['away_time']:
                self.is_active = False
            else:
                self.is_active = True

            current_window = get_window_title(hwnd)
            try:
                app, _, _, _ = get_app(hwnd)
            except Exception as e:
                logger.error(e)
                app = None
            if window != current_window and app:
                self.event_id = self.event_id + 1
                window = current_window
                new_data = {'event_id':self.event_id, 'start_time':str(self.current_timestamp), 'is_active':self.is_active,
                            'app': app, 'title': window}
                if data['data']:
                    data['data'][-1]['end_time'] = str(self.current_timestamp)
                data['data'].append(new_data)
                self.is_new = True
                print(new_data)
            else:
                if data['data']:
                    if data['data'][-1]['is_active'] != self.is_active:
                        data['data'][-1]['end_time'] = str(self.current_timestamp)
                        self.event_id = self.event_id + 1
                        new_data = {'event_id':self.event_id, 'start_time':str(self.current_timestamp), 'is_active':self.is_active,
                                    'app':data['data'][-1]['app'], 'title':data['data'][-1]['title']}
                        data['data'].append(new_data)
                        self.is_new = True
                        print(new_data)

            sent_deltatime = self.current_timestamp - self.sent_timestamp
            if sent_deltatime.seconds > self.policy['request_interval'] and self.is_new:
                # logger.info('activity request')
                status_code, response = _request_data('POST', self.urls['events'], data=data)
                if status_code == 200:
                    data['data'] = [data['data'][-1]]
                    self.is_new = False
                elif status_code == 400 and 'login' in response:
                    status_code, response = self.login_request()
                    if status_code == 200:
                        status_code, response = _request_data('POST', self.urls['events'], data=data)
                        if status_code == 200:
                            data['data'] = [data['data'][-1]]
                            self.is_new = False

                self.sent_timestamp = self.current_timestamp

            self.screenshot()
            QTest.qWait(self.policy['monitoring_interval'] * 1000)

    def screenshot(self):

        capture_deltatime = self.current_timestamp - self.capture_timestamp
        if capture_deltatime.seconds > self.policy['screenshot_interval'] and self.is_active:
            img = ImageGrab.grab(all_screens=True)  # multiscreen을 대응하기 위해 all_screens=True로 설정
            img = img.resize((int(img.width / self.policy['img_ratio']), int(img.height / self.policy['img_ratio'])))

            # screenshot path 확인
            if os.path.exists(os.getcwd() + '/screenshot/%s/%s/' % (self.group, self.user_id)):
                pass
            else:
                os.makedirs(os.getcwd() + '/screenshot/%s/%s/' % (self.group, self.user_id))
            file_name = str(self.current_timestamp).replace(':', '-').split('.')[0]
            file_path = os.getcwd() + '/screenshot/%s/%s/' % (self.group, self.user_id) + file_name + '.png'
            img.save(file_path)
            files = {'media': open(file_path, 'rb')}
            # logger.info('screenshot request')
            status_code, response = _request_data('POST', self.urls['screenshot'], files=files)
            if status_code == 400 and 'login' in response:
                status_code, response, self.login_request()
                if status_code == 200:
                    _request_data('POST', self.urls['screenshot'], files=files)
            self.capture_timestamp = self.current_timestamp

def set_logger():
    logger = logging.getLogger()
    fomatter = logging.Formatter(
        '[%(levelname)s|%(lineno)s] %(asctime)s > %(message)s')  # 로그를 남길 방식으로 "[로그레벨|라인번호] 날짜 시간,밀리초 > 메시지" 형식의 포매터를 만든다
    logday = datetime.today().strftime("%Y%m%d")  # 로그 파일 네임에 들어갈 날짜를 만듬 (YYYYmmdd 형태)

    fileMaxByte = 1024 * 1024 * 100  # 파일 최대 용량인 100MB를 변수에 할당 (100MB, 102,400KB)
    if os.path.exists(os.getcwd() + '/log'):
        pass
    else:
        os.makedirs(os.getcwd() + '/log')
    fileHandler = logging.handlers.RotatingFileHandler('./log/activity_' + str(logday) + '.log', maxBytes=fileMaxByte,
                                                       backupCount=10)  # 파일에 로그를 출력하는 핸들러 (100MB가 넘으면 최대 10개까지 신규 생성)
    streamHandler = logging.StreamHandler()

    fileHandler.setFormatter(fomatter)
    streamHandler.setFormatter(fomatter)

    logger.addHandler(fileHandler)
    logger.addHandler(streamHandler)

    logger.setLevel(logging.INFO)
    return logger

def _request_data(verb, url, params=None, headers=None, data=None, files=None):
    try:
        if data is not None:
            r = session.request(verb, url, params=params, headers=headers, json=data, files=files, timeout=3.0)
        else:
            r = session.request(verb, url, params=params, headers=headers, files=files, timeout=3.0)
    except Exception as e:
        logger.info(e)
        if params:
            logger.info(str(params))
        if data:
            logger.info(str(data))
        return 900, None
    else:
        data = r.content
        data = data.decode('utf-8')

        if r.status_code != 200:
            logger.info('Error Code: %s, %s' % (str(r.status_code), data))
            if params:
                logger.info(str(params))
        return r.status_code, data

def get_app(hwnd) -> Optional[str]:
    """Get application path given hwnd."""
    path = None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    for p in c.query('SELECT * FROM Win32_Process WHERE ProcessId = %s' % str(pid)):
        window_app = p.Name
        path = p.ExecutablePath
        csName = p.CSName
        windowsVersion = p.WindowsVersion
        break
    return window_app, path, csName, windowsVersion

def get_window_title(hwnd):
    return win32gui.GetWindowText(hwnd)

def get_active_window_handle():
    hwnd = win32gui.GetForegroundWindow()
    return hwnd

def get_window_list():    # 열려있는 창의 이름 확인
    def callback(hwnd, hwnd_list: list):
        title = win32gui.GetWindowText(hwnd)
        if win32gui.IsWindowEnabled(hwnd) and win32gui.IsWindowVisible(hwnd) and title:
            hwnd_list.append((title, hwnd))
        return True
    output = []
    win32gui.EnumWindows(callback, output)
    return output

def get_browser_tab_url(browser: str):
    """
    Get browser tab url, browser must already open
    :param browser: Support 'Edge' 'Google Chrome' and other Chromium engine browsers
    :return: Current tab url
    """
    if browser.lower() == 'edge':
        addr_bar = auto.EditControl(AutomationId='addressEditBox')
    else:
        win = auto.PaneControl(Depth=1, ClassName='Chrome_WidgetWin_1', SubName=browser)
        temp = win.PaneControl(Depth=1, Name=browser).GetChildren()[1].GetChildren()[0]
        for bar in temp.GetChildren():
            last = bar.GetLastChildControl()
            if last and last.Name != '':
                break
        addr_bar = bar.GroupControl(Depth=1, Name='').EditControl()
    url = addr_bar.GetValuePattern().Value
    return url

class LastInputInfo(Structure):
    _fields_ = [
        ("cbSize", UINT),
        ("dwTime", DWORD)
    ]

def _getLastInputTick() -> int:
    prototype = WINFUNCTYPE(BOOL, POINTER(LastInputInfo))
    paramflags = ((1, "lastinputinfo"), )
    c_GetLastInputInfo = prototype(("GetLastInputInfo", ctypes.windll.user32), paramflags)  # type: ignore

    l = LastInputInfo()
    l.cbSize = ctypes.sizeof(LastInputInfo)
    assert 0 != c_GetLastInputInfo(l)
    return l.dwTime

def _getTickCount() -> int:
    prototype = WINFUNCTYPE(DWORD)
    paramflags = ()
    c_GetTickCount = prototype(("GetTickCount", ctypes.windll.kernel32), paramflags)  # type: ignore
    return c_GetTickCount()

def seconds_since_last_input():
    seconds_since_input = (_getTickCount() - _getLastInputTick()) / 1000
    return seconds_since_input

logger = set_logger()

logger.info('activity start!!!')
app = QApplication(sys.argv)

form = LoginForm()
form.show()

sys.exit(app.exec_())