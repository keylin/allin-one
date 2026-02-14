-- PostgreSQL 初始化脚本
-- 由 docker-entrypoint-initdb.d 自动执行

CREATE USER allinone WITH PASSWORD 'allinone';
CREATE DATABASE allinone OWNER allinone;
