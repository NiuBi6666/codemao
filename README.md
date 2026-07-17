# codemao 学生 ID 查询

面向授权人员的学生信息批量查询系统。名单由管理员上传 Excel 维护。

## 功能

- 按姓名批量查询 ID，按 ID 批量查询学生信息
- 输入自动去重，重名时显示性别、年龄、年级和班级
- 查询结果复制与 CSV 导出
- 账号密码登录，连续失败 5 次锁定 15 分钟
- 可配置角色与权限，支持用户启用、停用和重置密码
- Excel 名单校验与事务式完整替换
- 登录、查询、名单和权限操作审计
- CSRF、会话 Cookie 和常用安全响应头

固定权限项包括查询学生、管理名单、管理用户与权限、查看审计日志。系统预置“查询员”“名单管理员”“系统管理员”三个角色。

## Excel 格式

第一个工作表第一行必须依次为：

| 用户ID | 姓名 | 性别 | 年龄 | 年级 | 班级名称 |
| --- | --- | --- | --- | --- | --- |

用户 ID 与姓名不能为空，用户 ID 不能重复。姓名允许重复，查询时返回全部候选。

## 部署

1. 复制 .env.example 为 .env，设置随机 SECRET_KEY 和管理员密码。
2. 将初始 Excel 放入 imports 目录；该目录不会提交到 Git。
3. 启动并检查服务：

       docker compose up -d --build
       docker compose ps
       curl http://127.0.0.1/healthz

运行数据保存在 data/codemao.sqlite3。生产环境应配置域名与 HTTPS，并将 COOKIE_SECURE 改为 true。

## 测试

    python -m unittest discover -v

## 备份与迁移

    ./ops/migration-export.sh
    ./ops/migration-restore.sh --verify-only /path/codemao-migration-时间.tar.gz

完整的新服务器迁移步骤见 MIGRATION.md。迁移归档包含学生数据和密钥，不得提交到 Git 或公共存储。

## 更新后的异步备份

每次 Git commit 或 pull/merge 会异步排队完整迁移备份。部署完成并确认健康后再执行：

    ./ops/trigger-async-backup.sh post-deploy

该命令立即返回，实际备份由 systemd 后台执行。
