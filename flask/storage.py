"""Database connections shared by the Flask app and session/auth storage."""
import re
import sqlite3


class PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @staticmethod
    def _translate(sql):
        """Translate SQLite qmark parameters without touching quoted question marks."""
        output = []
        quote = None
        i = 0
        while i < len(sql):
            char = sql[i]
            if quote:
                output.append(char)
                if char == quote:
                    if i + 1 < len(sql) and sql[i + 1] == quote:
                        output.append(sql[i + 1])
                        i += 1
                    else:
                        quote = None
            elif char in ("'", '"'):
                quote = char
                output.append(char)
            elif char == '?':
                output.append('%s')
            else:
                output.append(char)
            i += 1
        return ''.join(output)

    def execute(self, sql, params=None):
        sql = self._translate(sql)
        if re.fullmatch(r'\s*BEGIN\s+IMMEDIATE\s*;?\s*', sql, re.IGNORECASE):
            sql = 'BEGIN'
        if params is None:
            self._cursor.execute(sql)
        else:
            self._cursor.execute(sql, params)
        return self

    def executemany(self, sql, seq_of_params):
        self._cursor.executemany(self._translate(sql), seq_of_params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return None

    @property
    def description(self):
        return self._cursor.description


class PostgresConnection:
    dialect = 'postgres'

    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        from psycopg2.extras import DictCursor
        return PostgresCursor(self._connection.cursor(cursor_factory=DictCursor))

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def executemany(self, sql, seq_of_params):
        return self.cursor().executemany(sql, seq_of_params)

    def commit(self):
        return self._connection.commit()

    def rollback(self):
        return self._connection.rollback()

    @property
    def in_transaction(self):
        return self._connection.info.transaction_status != 0

    def close(self):
        return self._connection.close()


def connect_database(config):
    """Open the configured app database without exposing connection credentials."""
    if config.get('USE_SQLITE'):
        conn = sqlite3.connect(config['SQLITE_PATH'], timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=20000')
        return conn

    database_url = config.get('DATABASE_URL')
    if not database_url:
        raise RuntimeError('Replit SQL Database is not connected (DATABASE_URL is missing).')

    import psycopg2
    from psycopg2.extras import DictCursor
    raw_connection = psycopg2.connect(
        database_url,
        cursor_factory=DictCursor,
        connect_timeout=10,
        application_name='ege-trainer',
    )
    raw_connection.autocommit = False
    return PostgresConnection(raw_connection)
