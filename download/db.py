import mysql.connector
from mysql.connector import errorcode
from config.config import (
    THCPN_DB_CONFIG
)

DB_HOST = THCPN_DB_CONFIG["DB_HOST"]
DB_PORT = THCPN_DB_CONFIG["DB_PORT"]
DB_DATABASE = THCPN_DB_CONFIG["DB_DATABASE"]
DB_USERNAME = THCPN_DB_CONFIG["DB_USERNAME"]
DB_PASSWORD = THCPN_DB_CONFIG["DB_PASSWORD"]


def create_engine(user, password, database, host="127.0.0.1", port=3306, **kw):
    params = dict(user=user, password=password, database=database, host=host, port=port)
    defaults = dict(
        use_unicode=True,
        charset="utf8",
        collation="utf8_general_ci",
        autocommit=False,
        use_pure=True  # 强制使用纯Python实现，避免C扩展问题
    )
    for k, v in defaults.items():
        params[k] = kw.pop(k, v)
    params.update(kw)
    params["buffered"] = True

    try:
        engine = mysql.connector.connect(**params)
        return engine
    except mysql.connector.Error as err:
        # 使用MySQL Connector的专用错误处理
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            error_msg = "用户名或密码错误"
        elif err.errno == errorcode.ER_BAD_DB_ERROR:
            error_msg = "数据库不存在"
        elif err.errno == errorcode.CR_CONN_HOST_ERROR:
            error_msg = "无法连接到数据库服务器"
        else:
            error_msg = f"数据库连接错误: {err}"
        raise Exception(f"MySQL连接失败: {error_msg}")
    except Exception as e:
        # 处理其他类型的错误
        error_msg = f"MySQL连接失败: {str(e)}"
        error_msg += f" (错误类型: {type(e).__name__})"
        raise Exception(error_msg)


class database_resource:
    def __init__(
        self,
        user=DB_USERNAME,
        password=DB_PASSWORD,
        database=DB_DATABASE,
        host=DB_HOST,
        port=DB_PORT,
    ):
        self.user = user
        self.password = password
        self.database = database
        self.host = host
        self.port = port

    def __enter__(self):
        self.conn = create_engine(
            self.user, self.password, self.database, self.host, self.port
        )
        self.cursor = self.conn.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.commit()
        self.cursor.close()
        self.conn.close()
