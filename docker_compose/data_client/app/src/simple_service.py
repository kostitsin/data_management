"""
Умеет выполнять классификацию клиентов по трём фичам

Запускаем из python3:
    python3 service.py
Проверяем работоспособность:
    curl http://0.0.0.0:5001/
"""
import http.server
import json
import logging
import os
import socketserver
from http import HTTPStatus

import psycopg2
from msgpack import packb, unpackb
from redis import Redis
from datetime import datetime

# файл, куда посыпятся логи модели
FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(filename="/www/app/service.log", level=logging.INFO, format=FORMAT)


class Handler(http.server.SimpleHTTPRequestHandler):
    """Простой http-сервер"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_response(self) -> dict:
        response = {'health-check': 'ok'}
        params_parsed = self.path.split('?')
        if self.path.startswith('/ping/'):
            response = {'message': 'pong'}
        # Реализуем API profile
        elif self.path.startswith('/user/profile'):
            response = self.get_user_profile()
        # Реализуем API /user/watchhistory/user_id
        elif self.path.startswith('/user/watchhistory'):
            response = self.get_user_watch_history()
        return response

    def get_user_profile(self) -> dict:
        user_id = self.path.replace('?year=', '/').replace('&month=', '/').split('/')[-3::]
        logging.info(f'Поступил запрос по пользователю user_id={user_id[0]} за {user_id[2]} месяц {user_id[1]} года')
        redis_profile_key = f'profile:{user_id[0], user_id[1], user_id[2]}'
        # проверяем наличие объекта в Redis-кеше
        if redis_interactor.is_cached(redis_profile_key):
            logging.info(f'Профиль пользователя user_id={user_id[0],user_id[1], user_id[2]} присутствует в кеше')
            response_list = redis_interactor.get_data(redis_profile_key)
        # если ключ отcутствует в кеше - выполняем "тяжёлый" SQL-запрос в Postgres
        else:
            logging.info(f'Профиль пользователя user_id={user_id[0]} за {user_id[2]} месяц {user_id[1]} года отсутствует в кеше, выполняем запрос к Postgres')
            user_profile = [None, None]  # [num_rating, avg_rating]
            try:
                user_profile = postgres_interactor.get_sql_result(
                    f"""
                    SELECT userid, rating, timestamp
                    FROM ratings
                    WHERE userId = {user_id[0]}"""
                )
            except Exception as e:
                logging.info(f'Произошла ошибка запроса к Postgres:\n{e}')
            
            response_list = list()
            for user in user_profile:
                if (int(datetime.utcfromtimestamp(int(user[2])).strftime('%Y')) == int(user_id[1])) and (int(datetime.utcfromtimestamp(int(user[2])).strftime('%m')) == int(user_id[2])):
                    response = {'user_id': user_id[0],
                     'month': user_id[2],
                     'year':user_id[1], 'rating':int(user[1])}
                    response_list.append(response)
                    logging.info(f'Сохраняем профиль пользователя user_id={user_id[0]} в Redis-кеш')
                    redis_interactor.set_data(redis_profile_key, response_list)
                else:
                    response = {'message': 'No ratings found'}
                    response_list.append(response)
                    redis_interactor.set_data(redis_profile_key, response_list)
                    logging.info(f'Пользователь с user_id={user_id[0]} не делал оценок в {user_id[2]} месяце {user_id[1]} года')
                    break
        return response_list

    def get_user_watch_history(self) -> dict:
        user_id = self.path.split('/')[-1]
        logging.info(f'Поступил запрос на историю пользователя user_id={user_id}')
        redis_history_key = f'history:{user_id}'
        if redis_interactor.is_cached(redis_history_key):
            logging.info(f'История пользователя user_id={user_id} присутствует в кеше')
            user_hist_list = redis_interactor.get_data(redis_history_key)
        else:
            logging.info(f'История пользователя user_id={user_id} отсутствует в кеше, выполняем запрос к Postgres')
            user_history = [None, None]
            try:
                user_history = postgres_interactor.get_sql_result(
                    f"""
                    SELECT movieid, rating, timestamp 
                    FROM ratings
                    WHERE userid = {user_id}"""
                    )
            except Exception as e:
                logging.info(f'Произошла ошибка запроса к Postgres:\n{e}')

        user_hist_list = list()
        
        for user in user_history:
            history = {"movie_id": int(user[0]), "rating": int(user[1]), "timestamp": user[2]}
            user_hist_list.append(history)

        logging.info(f'Сохраняем историю пользователя user_id={user_id} в Redis-кеш')
        redis_interactor.set_data(redis_history_key, user_hist_list)

        return user_hist_list

    def do_GET(self):
        # заголовки ответа
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.get_response()).encode())


class PostgresStorage:
    def __init__(self):
        # подключение к Postgres
        params = {
            "host": os.environ['APP_POSTGRES_HOST'],
            "port": os.environ['APP_POSTGRES_PORT'],
            "user": 'postgres'
        }
        self.conn = psycopg2.connect(**params)

        # дополнительные настройки
        psycopg2.extensions.register_type(
            psycopg2.extensions.UNICODE,
            self.conn
        )
        self.conn.set_isolation_level(
            psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
        )
        self.cursor = self.conn.cursor()

    def get_sql_result(self, sql_str):
        """Исполняем SQL и возвращаем PandasDF"""
        # исполняем SQL
        self.cursor.execute(sql_str)
        # получаем результат запроса
        query_data = [a for a in self.cursor.fetchall()]
        # коммит необязательно, но для порядка необходим
        self.conn.commit()
        return query_data


class RedisStorage:
    def __init__(self):
        REDIS_CONF = {
            "host": os.environ['APP_REDIS_HOST'],
            "port": os.environ['APP_REDIS_PORT'],
            "db": 0
        }
        self.storage = Redis(**REDIS_CONF)

    def set_data(self, redis_key, data):
        self.storage.set(redis_key, packb(data, use_bin_type=True))

    def get_data(self, redis_key):
        result = dict()
        redis_data = self.storage.get(redis_key)
        if redis_data is not None:
            result = unpackb(redis_data, raw=False)
        return result

    def is_cached(self, redis_key: str) -> bool:
        return self.storage.exists(redis_key)


postgres_interactor = PostgresStorage()
logging.info('Инициализирован класс для работы с Postgres')
redis_interactor = RedisStorage()
logging.info('Инициализирован класс для работы с Redis')

if __name__ == '__main__':
    classifier_service = socketserver.TCPServer(('', 5000), Handler)
    logging.info('Приложение инициализировано')
    classifier_service.serve_forever()
