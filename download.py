from bs4 import BeautifulSoup
from multiprocessing.pool import Pool
from urllib.parse import urlparse
from getpass import getpass
from tqdm import tqdm
import errno
import os
import re
import requests

BASE_URL = 'https://olympia.id'


class Olympia(requests.Session):
    URL_LOGIN_PAGE = f'{BASE_URL}/login/index.php'
    URL_DASHBOARD = f'{BASE_URL}/my/'
    URL_WEB_SERVICE_API = f'{BASE_URL}/lib/ajax/service.php'
    URL_COURSE_VIEW = f'{BASE_URL}/course/view.php'
    URL_QUIZ_REPORT = f'{BASE_URL}/mod/quiz/report.php'
    URL_QUIZ_REVIEW = f'{BASE_URL}/mod/quiz/review.php'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.sesskey = None

    def login(self, username, password):
        r = self.get(self.URL_LOGIN_PAGE)
        s = BeautifulSoup(r.text, 'html.parser')

        logintoken_input = s.find('input', attrs={'name': 'logintoken'})
        assert logintoken_input is not None, 'Can\'t find login token'

        login_data = {
            'username': username,
            'password': password,
            'logintoken': logintoken_input['value'],
        }
        r = self.post(self.URL_LOGIN_PAGE, login_data)

        # Retrieving session key for api call
        r = self.get(self.URL_DASHBOARD)
        m = re.search('"sesskey":"([^"]+)"', r.text)
        assert m is not None, 'Failed to retrieve session key'
        self.sesskey = m.group(1)

    def __web_service_api(self, methodname, args={}):
        data = [{
            'index': 0,
            'methodname': methodname,
            'args': args,
        }]
        r = self.post(f'{self.URL_WEB_SERVICE_API}?sesskey={self.sesskey}', json=data)
        return r.json()

    def get_courses(self):
        if self.sesskey is None:
            raise Exception('Need to login before using this method')

        methodname = 'core_course_get_enrolled_courses_by_timeline_classification'
        args = {
            'offset': 0,
            'limit': 24,
            'classification': 'all',
            'sort': 'fullname'
        }

        result = []
        res = self.__web_service_api(methodname, args)
        for course_data in res[0]['data']['courses']:
            course_id = course_data['id']
            course_name = course_data['fullname']
            result.append((course_id, course_name))
        return result

    def get_course_quizes(self, course_id):
        if self.sesskey is None:
            raise Exception('Need to login before using this method')

        r = self.get(f'{self.URL_COURSE_VIEW}?id={course_id}')
        s = BeautifulSoup(r.text, 'html.parser')

        result = []
        quizes = s.find_all('li', attrs={'class': 'activity quiz modtype_quiz'})
        if quizes is None or len(quizes) == 0:
            raise Exception('No quiz on course')
        for quiz in quizes:
            link = quiz.find('a')['href']
            quiz_id = int(re.search('id=(\\d+)', link).group(1))
            quiz_name = str(quiz.find('span', attrs={'class': 'instancename'}).contents[0])
            result.append((quiz_id, quiz_name))
        result.sort()
        return result

    def get_quiz_report(self, quiz_id):
        # NOTE: this will return the attempt with HIGHEST score, unique for each user
        #       notice that each quiz can have multiple attempts
        if self.sesskey is None:
            raise Exception('Need to login before using this method')

        data = {
            'id': quiz_id,
            'mode': 'overview',
            'sesskey': self.sesskey,
            '_qf__quiz_overview_settings_form': 1,
            'mform_isexpanded_id_preferencespage': 1,
            'mform_isexpanded_id_preferencesuser': 1,
            'attempts': 'enrolled_with',
            'stateinprogress': 1,
            'stateoverdue': 1,
            'statefinished': 1,
            'stateabandoned': 1,
            'onlygraded': 1,
            'onlyregraded': 0,
            'pagesize': 600,
            'slotmarks': 1,
        }

        r = self.post(self.URL_QUIZ_REPORT, data)
        s = BeautifulSoup(r.text, 'html.parser')

        result = []
        attempt_cells = s.find_all('td', attrs={'class': 'cell c2 bold'})
        if attempt_cells is None or len(attempt_cells) == 0:
            raise Exception('No attempt found')
        for attempt_cell in attempt_cells:
            if (len(attempt_cell.contents) == 3):
                user_name = attempt_cell.contents[0].string
                user_attempt_link = attempt_cell.contents[2]['href']
                user_attempt_id = int(re.search('attempt=(\\d+)', user_attempt_link).group(1))
                result.append((user_attempt_id, user_name))
            else:
                # This should be "Overall" row
                pass
        return result

    def get_quiz_attempt_submissions(self, attempt_id):
        # NOTE: this will return the LAST submission of the attempt
        #       notice that each attempt, user can retry the question
        r = self.get(f'{self.URL_QUIZ_REVIEW}?attempt={attempt_id}')
        s = BeautifulSoup(r.text, 'html.parser')

        submissions = []
        attachment_blocks = s.find_all('div', attrs={'class': 'attachments'})
        if attachment_blocks is None or len(attachment_blocks) == 0:
            raise Exception('No submission found')
        for attachment_block in attachment_blocks:
            if attachment_block.p is not None:
                submissions.append(attachment_block.p.a['href'])
        return submissions


def download_file(url, filepath=None, session=None):
    if filepath is None:
        url_parsed = urlparse(url)
        filepath = os.path.basename(url_parsed.path)

    r = None
    if session is None:
        r = requests.get(url, stream=True)
    else:
        r = session.get(url, stream=True)

    if not os.path.exists(os.path.dirname(filepath)):
        try:
            os.makedirs(os.path.dirname(filepath))
        except OSError as exc:  # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise

    with open(filepath, 'wb+') as f:
        for ch in r:
            f.write(ch)


if __name__ == "__main__":
    olympia_session = Olympia()

    username = ''  # input('Username: ')
    password = ''  # getpass('Password: ')
    olympia_session.login(username, password)

    courses = olympia_session.get_courses()
    for course_id, course_name in courses:
        print('{:3d} {}'.format(course_id, course_name))

    course_id = int(input('pilih id course: '))
    quizes = olympia_session.get_course_quizes(course_id)
    for quiz_id, quiz_name in quizes:
        print('{:6d} {}'.format(quiz_id, quiz_name))

    quiz_id = int(input('pilih id quiz: '))
    quiz_name = ''
    for _id, _name in quizes:
        if _id == quiz_id:
            quiz_name = _name
    attempts = olympia_session.get_quiz_report(quiz_id)
    download_attempts = []
    for user_attempt_id, user_name in attempts:
        try:
            user_attempt_links = olympia_session.get_quiz_attempt_submissions(user_attempt_id)

            for link in user_attempt_links:
                url_parsed = urlparse(link)
                filename = os.path.basename(url_parsed.path)
                filepath = f'out/{course_id}/{quiz_id} {quiz_name}/{user_name}/{filename}'
                print('{:7d} {} {}'.format(user_attempt_id, user_name, link))
                download_attempts.append((link, filepath))
        except Exception as e:
            print('{:7d} {} {}'.format(user_attempt_id, user_name, str(e)))

    # Download 10 files at a time
    download_pools = Pool(10)
    async_results = []
    for url, filepath in download_attempts:
        async_results.append(download_pools.apply_async(download_file, (url, filepath, olympia_session)))
    for async_result in tqdm(async_results):
        async_result.wait()
