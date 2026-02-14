-- PostgreSQL 初始化脚本
-- 由 docker-entrypoint-initdb.d 自动执行

CREATE USER allinone WITH PASSWORD 'allinone';
CREATE DATABASE allinone OWNER allinone;

CREATE USER miniflux WITH PASSWORD 'miniflux';
CREATE DATABASE miniflux OWNER miniflux;
GRANT ALL PRIVILEGES ON DATABASE miniflux TO miniflux;
ALTER USER miniflux WITH SUPERUSER;
