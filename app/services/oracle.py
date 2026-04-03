import python_oracledb as oracledb
import os

pool = oracledb.create_pool(
    user=os.getenv("ORACLE_USER"),
    password=os.getenv("ORACLE_PASSWORD"),
    dsn=f"{os.getenv('ORACLE_HOST')}:{os.getenv('ORACLE_PORT', '1521')}/{os.getenv('ORACLE_DB', 'XEPDB1')}",
    min=2, max=10, increment=1
)

def get_connection():
    return pool.acquire()