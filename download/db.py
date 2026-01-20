import mysql.connector
from typing import List, Tuple
from mysql.connector import errorcode

# v2.3.1+
import logging
import time
import re
from datetime import datetime
from typing import Any, Dict, Optional
import json
try:
    import bcrypt
except Exception:
    bcrypt = None
logger = logging.getLogger(__name__)

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

# ============================
# 通用工具：终端详细日志 + 错误结构
# v2.3.1+ USER ADMIN CRUD
def _ts_ms() -> int:
    return int(time.time() * 1000)

def _safe_params(params: Optional[tuple]) -> tuple:
    """脱敏：避免把密码/密钥直接打到终端日志"""
    if not params:
        return ()
    safe = []
    for p in params:
        if isinstance(p, str) and len(p) > 0:
            # 你也可以按字段位置进一步精确脱敏，这里先通用处理
            if "password" in p.lower() or "secret" in p.lower():
                safe.append("***")
            else:
                safe.append(p)
        else:
            safe.append(p)
    return tuple(safe)

def _ok(**kw) -> Dict[str, Any]:
    d = {"ok": True, "error": None}
    d.update(kw)
    return d

def _err(code: str, message: str, detail: Optional[str] = None, **kw) -> Dict[str, Any]:
    d = {
        "ok": False,
        "error": {"code": code, "message": message, "detail": detail},
    }
    d.update(kw)
    return d

def _is_phone(keyword: str) -> bool:
    """判定是否是 phone：支持 +8613... 这种"""
    kw = (keyword or "").strip()
    return bool(re.match(r"^\+?\d{5,}$", kw))

def _hash_password_bcrypt(password_plain: str) -> str:
    """bcrypt 加密：返回 hash 字符串（utf-8）"""
    if bcrypt is None:
        raise RuntimeError("bcrypt 未安装：请先安装 bcrypt")
    if password_plain is None:
        raise RuntimeError("password 不能为空")
    pw = password_plain.encode("utf-8")
    hashed = bcrypt.hashpw(pw, bcrypt.gensalt())
    return hashed.decode("utf-8")
# ============================

# ============================
# 设备查询：给 GUI 名称搜索用
# v2.0 刘坦然 26/01/08
# ============================

def search_devices_by_name(keyword: str, limit: int = 30) -> List[Tuple[int, str]]:
    """
    模糊搜索设备名（用于下拉建议）
    返回 [(id, name), ...]
    """
    kw = (keyword or "").strip()
    if not kw:
        return []

    sql = (
        "SELECT `id`, `name` "
        "FROM `devices` "
        "WHERE `deleted_at` IS NULL AND `name` LIKE %s "
        "ORDER BY `name` "
        "LIMIT %s"
    )
    like_kw = f"%{kw}%"
    try:
        with database_resource() as cursor:
            cursor.execute(sql, (like_kw, int(limit)))
            rows = cursor.fetchall() or []
            return [(int(r[0]), str(r[1])) for r in rows]
    except Exception:
        return []

def get_device_by_exact_name(name: str, limit: int = 20) -> List[Tuple[int, str]]:
    """
    精确匹配设备名（用户输入完整名字时用）
    返回 [(id, name), ...]
    """
    n = (name or "").strip()
    if not n:
        return []

    sql = (
        "SELECT `id`, `name` "
        "FROM `devices` "
        "WHERE `deleted_at` IS NULL AND `name` = %s "
        "LIMIT %s"
    )
    try:
        with database_resource() as cursor:
            cursor.execute(sql, (n, int(limit)))
            rows = cursor.fetchall() or []
            return [(int(r[0]), str(r[1])) for r in rows]
    except Exception:
        return []

# ============================
# 通用工具：终端详细日志 + 错误结构
# v2.3.1+ USER ADMIN CRUD
def find_users_by_name_or_phone(keyword: str) -> Dict[str, Any]:
    """
    通过 name 或 phone 查找用户
    - phone：唯一，精确匹配
    - name：可能重复，返回多条（上层必须做错误处理）
    """
    t0 = _ts_ms()
    kw = (keyword or "").strip()
    logger.info(f"[USER_ADMIN][DB_CALL] find_users_by_name_or_phone keyword={kw!r}")

    if not kw:
        logger.warning("[USER_ADMIN][VALIDATE] empty keyword")
        return _err("INVALID_INPUT", "请输入名字或电话")

    mode = "phone" if _is_phone(kw) else "name"
    try:
        if mode == "phone":
            sql = (
                "SELECT id, name, phone, email, password, created_at, updated_at, avatar "
                "FROM users WHERE phone = %s LIMIT 5"
            )
            params = (kw,)
        else:
            sql = (
                "SELECT id, name, phone, email, password, created_at, updated_at, avatar "
                "FROM users WHERE name = %s LIMIT 20"
            )
            params = (kw,)

        logger.info(f"[USER_ADMIN][SQL] mode={mode} sql={sql} params={_safe_params(params)}")

        with database_resource() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall() or []

        users = []
        for r in rows:
            users.append({
                "id": int(r[0]),
                "name": r[1],
                "phone": r[2],
                "email": r[3],
                "password_hash": r[4],   # 只返回 hash
                "created_at": r[5],
                "updated_at": r[6],
                "avatar": r[7],
            })

        cost = _ts_ms() - t0
        logger.info(f"[USER_ADMIN][DB_RESULT] mode={mode} count={len(users)} cost_ms={cost}")
        return _ok(mode=mode, keyword=kw, count=len(users), users=users)

    except Exception as e:
        logger.exception("[USER_ADMIN][DB_ERROR] find_users_by_name_or_phone failed")
        return _err("DB_ERROR", "查询用户失败", detail=str(e), mode=mode, keyword=kw, count=0, users=[])

def create_user(name: str, phone: str, email: Optional[str], password_plain: str) -> Dict[str, Any]:
    """
    新增用户：
    - phone 唯一，不允许重复
    - password 使用 bcrypt 加密后写入 users.password
    """
    t0 = _ts_ms()
    logger.info(f"[USER_ADMIN][DB_CALL] create_user name={name!r} phone={phone!r} email={email!r}")

    n = (name or "").strip()
    p = (phone or "").strip()
    em = (email or "").strip() if email is not None else None
    pw = (password_plain or "").strip()

    if not n or not p or not pw:
        logger.warning("[USER_ADMIN][VALIDATE] missing required fields")
        return _err("INVALID_INPUT", "name / phone / password 不能为空")

    if not _is_phone(p):
        logger.warning("[USER_ADMIN][VALIDATE] invalid phone format")
        return _err("INVALID_INPUT", "phone 格式不正确")

    try:
        # 1) phone 查重
        sql_check = "SELECT id FROM users WHERE phone = %s LIMIT 1"
        with database_resource() as cursor:
            logger.info(f"[USER_ADMIN][SQL] check_phone sql={sql_check} params={_safe_params((p,))}")
            cursor.execute(sql_check, (p,))
            exists = cursor.fetchone()

        if exists:
            logger.warning(f"[USER_ADMIN][BUSINESS] phone duplicate phone={p!r} user_id={exists[0]}")
            return _err("PHONE_DUPLICATE", "该 phone 已存在，禁止重复添加")

        # 2) bcrypt hash
        pw_hash = _hash_password_bcrypt(pw)
        logger.info("[USER_ADMIN][SECURITY] bcrypt hashed password ok")

        # 3) insert
        sql_ins = (
            "INSERT INTO users (name, phone, email, password, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        params = (n, p, em, pw_hash)
        logger.info(f"[USER_ADMIN][SQL] insert_user sql={sql_ins} params={('**name**', '**phone**', em, '***')}")

        with database_resource() as cursor:
            cursor.execute(sql_ins, params)
            new_id = cursor.lastrowid

        cost = _ts_ms() - t0
        logger.info(f"[USER_ADMIN][DB_RESULT] create_user ok user_id={new_id} cost_ms={cost}")
        return _ok(user_id=int(new_id))

    except Exception as e:
        logger.exception("[USER_ADMIN][DB_ERROR] create_user failed")
        return _err("DB_ERROR", "新增用户失败", detail=str(e))

def update_user_info(user_id: int, name: Optional[str], email: Optional[str], password_plain: Optional[str]) -> Dict[str, Any]:
    """
    更新用户信息：
    - 允许改：name, email, password
    - 不允许改：phone（不在入参）
    - 更新 updated_at
    """
    t0 = _ts_ms()
    logger.info(f"[USER_ADMIN][DB_CALL] update_user_info user_id={user_id} name={name!r} email={email!r} pw={'***' if password_plain else None}")

    if not user_id or int(user_id) <= 0:
        return _err("INVALID_INPUT", "user_id 不合法")

    fields = []
    params = []

    n = (name or "").strip() if name is not None else None
    em = (email or "").strip() if email is not None else None
    pw = (password_plain or "").strip() if password_plain is not None else None

    if n is not None and n != "":
        fields.append("name = %s")
        params.append(n)

    if email is not None:
        # 允许置空 email：传入 "" 时置为 NULL
        if em == "":
            fields.append("email = NULL")
        else:
            fields.append("email = %s")
            params.append(em)

    if pw is not None:
        if pw == "":
            return _err("INVALID_INPUT", "password 不能为空")
        pw_hash = _hash_password_bcrypt(pw)
        fields.append("password = %s")
        params.append(pw_hash)
        logger.info("[USER_ADMIN][SECURITY] bcrypt hashed new password ok")

    if not fields:
        return _err("INVALID_INPUT", "没有任何可更新字段")

    # always update updated_at
    fields.append("updated_at = CURRENT_TIMESTAMP")

    try:
        sql = f"UPDATE users SET {', '.join(fields)} WHERE id = %s LIMIT 1"
        params.append(int(user_id))

        # 参数脱敏打印
        safe_params = []
        for x in params:
            if isinstance(x, str) and len(x) > 30:
                safe_params.append("***")  # 认为是 hash
            else:
                safe_params.append(x)

        logger.info(f"[USER_ADMIN][SQL] update_user sql={sql} params={tuple(safe_params)}")

        with database_resource() as cursor:
            cursor.execute(sql, tuple(params))
            updated = cursor.rowcount

        cost = _ts_ms() - t0
        logger.info(f"[USER_ADMIN][DB_RESULT] update_user rows={updated} cost_ms={cost}")

        if updated == 0:
            return _err("USER_NOT_FOUND", "用户不存在或数据未变化", detail="updated_rows=0", updated_rows=0)

        return _ok(updated_rows=int(updated))

    except Exception as e:
        logger.exception("[USER_ADMIN][DB_ERROR] update_user_info failed")
        return _err("DB_ERROR", "修改用户失败", detail=str(e), updated_rows=0)

def list_bound_devices_for_user(user_id: int) -> Dict[str, Any]:
    """
    查询用户绑定设备：返回 device_id + device_name
    默认过滤 device_user.deleted_at IS NULL（如果历史有软删记录）
    """
    t0 = _ts_ms()
    logger.info(f"[USER_ADMIN][DB_CALL] list_bound_devices_for_user user_id={user_id}")

    if not user_id or int(user_id) <= 0:
        return _err("INVALID_INPUT", "user_id 不合法", bindings=[], count=0)

    sql = (
        "SELECT du.device_id, d.name, du.created_at "
        "FROM device_user du "
        "LEFT JOIN devices d ON d.id = du.device_id AND d.deleted_at IS NULL "
        "WHERE du.user_id = %s AND (du.deleted_at IS NULL) "
        "ORDER BY du.device_id ASC"
    )
    try:
        with database_resource() as cursor:
            logger.info(f"[USER_ADMIN][SQL] list_bindings sql={sql} params={_safe_params((int(user_id),))}")
            cursor.execute(sql, (int(user_id),))
            rows = cursor.fetchall() or []

        bindings = [{
            "device_id": int(r[0]),
            "device_name": r[1],
            "created_at": r[2],
        } for r in rows]

        cost = _ts_ms() - t0
        logger.info(f"[USER_ADMIN][DB_RESULT] list_bindings count={len(bindings)} cost_ms={cost}")
        return _ok(count=len(bindings), bindings=bindings)

    except Exception as e:
        logger.exception("[USER_ADMIN][DB_ERROR] list_bound_devices_for_user failed")
        return _err("DB_ERROR", "查询绑定设备失败", detail=str(e), bindings=[], count=0)

def add_device_binding(user_id: int, device_id: int) -> Dict[str, Any]:
    """
    添加 device_user 绑定：
    - 先确认 users.id 存在
    - 再确认 devices.id 存在且未删除
    - 再确认 device_user 不重复
    """
    t0 = _ts_ms()
    logger.info(f"[USER_ADMIN][DB_CALL] add_device_binding user_id={user_id} device_id={device_id}")

    if not user_id or int(user_id) <= 0 or not device_id or int(device_id) <= 0:
        return _err("INVALID_INPUT", "user_id / device_id 不合法")

    try:
        with database_resource() as cursor:
            # 1) user exists
            sql_user = "SELECT id FROM users WHERE id = %s LIMIT 1"
            logger.info(f"[USER_ADMIN][SQL] check_user sql={sql_user} params={(int(user_id),)}")
            cursor.execute(sql_user, (int(user_id),))
            if not cursor.fetchone():
                logger.warning("[USER_ADMIN][BUSINESS] user not found")
                return _err("USER_NOT_FOUND", "用户不存在")

            # 2) device exists
            sql_dev = "SELECT id, name FROM devices WHERE deleted_at IS NULL AND id = %s LIMIT 1"
            logger.info(f"[USER_ADMIN][SQL] check_device sql={sql_dev} params={(int(device_id),)}")
            cursor.execute(sql_dev, (int(device_id),))
            dev = cursor.fetchone()
            if not dev:
                logger.warning("[USER_ADMIN][BUSINESS] device not found")
                return _err("DEVICE_NOT_FOUND", "设备不存在或已删除")

            # 3) duplicate check
            sql_dup = (
                "SELECT id FROM device_user "
                "WHERE user_id = %s AND device_id = %s AND (deleted_at IS NULL) "
                "LIMIT 1"
            )
            logger.info(f"[USER_ADMIN][SQL] check_duplicate sql={sql_dup} params={(int(user_id), int(device_id))}")
            cursor.execute(sql_dup, (int(user_id), int(device_id)))
            if cursor.fetchone():
                logger.warning("[USER_ADMIN][BUSINESS] duplicate binding")
                return _err("DUPLICATE_BINDING", "该设备已绑定到该用户")

            # 4) insert
            sql_ins = (
                "INSERT INTO device_user (user_id, device_id, created_at, updated_at) "
                "VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
            logger.info(f"[USER_ADMIN][SQL] insert_binding sql={sql_ins} params={(int(user_id), int(device_id))}")
            cursor.execute(sql_ins, (int(user_id), int(device_id)))
            new_id = cursor.lastrowid

        cost = _ts_ms() - t0
        logger.info(f"[USER_ADMIN][DB_RESULT] add_binding ok id={new_id} cost_ms={cost}")
        return _ok(binding_id=int(new_id))

    except Exception as e:
        logger.exception("[USER_ADMIN][DB_ERROR] add_device_binding failed")
        return _err("DB_ERROR", "添加设备绑定失败", detail=str(e))

def delete_device_binding(user_id: int, device_id: int) -> Dict[str, Any]:
    """
    物理删除绑定：DELETE device_user WHERE user_id=? AND device_id=?
    返回 deleted_rows: 0/1
    """
    t0 = _ts_ms()
    logger.info(f"[USER_ADMIN][DB_CALL] delete_device_binding user_id={user_id} device_id={device_id}")

    if not user_id or int(user_id) <= 0 or not device_id or int(device_id) <= 0:
        return _err("INVALID_INPUT", "user_id / device_id 不合法", deleted_rows=0)

    sql = "DELETE FROM device_user WHERE user_id = %s AND device_id = %s"
    try:
        with database_resource() as cursor:
            logger.info(f"[USER_ADMIN][SQL] delete_binding sql={sql} params={(int(user_id), int(device_id))}")
            cursor.execute(sql, (int(user_id), int(device_id)))
            deleted = cursor.rowcount

        cost = _ts_ms() - t0
        logger.info(f"[USER_ADMIN][DB_RESULT] delete_binding rows={deleted} cost_ms={cost}")
        return _ok(deleted_rows=int(deleted))

    except Exception as e:
        logger.exception("[USER_ADMIN][DB_ERROR] delete_device_binding failed")
        return _err("DB_ERROR", "删除设备绑定失败", detail=str(e), deleted_rows=0)

# ============================

# ============================
# 设备查询：给 GUI id搜索用
# v2.1 刘坦然 26/01/08
# ============================

def search_devices_by_id(keyword: str, limit: int = 30) -> List[Tuple[int, str]]:
    """
    按设备ID检索（支持输入部分ID，例如输入 25 能匹配 2594）
    返回: [(id, name), ...]
    """
    kw = (keyword or "").strip()
    if not kw:
        return []

    sql = (
        "SELECT id, name FROM devices "
        "WHERE deleted_at IS NULL AND CAST(id AS CHAR) LIKE %s "
        "ORDER BY id ASC LIMIT %s"
    )

    like_kw = f"%{kw}%"
    with database_resource() as cursor:
        cursor.execute(sql, (like_kw, limit))
        rows = cursor.fetchall() or []
    return [(int(r[0]), str(r[1])) for r in rows]


def get_device_by_id(device_id: int) -> List[Tuple[int, str]]:
    """
    按设备ID精确获取（用于“添加”时用户直接输入ID）
    返回: [(id, name)] 或 []
    """
    sql = (
        "SELECT id, name FROM devices "
        "WHERE deleted_at IS NULL AND id = %s "
        "LIMIT 1"
    )
    with database_resource() as cursor:
        cursor.execute(sql, (device_id,))
        rows = cursor.fetchall() or []
    return [(int(r[0]), str(r[1])) for r in rows]

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(find_users_by_name_or_phone("123456789"))
