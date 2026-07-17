# 服务器迁移手册

项目采用 Docker Compose。迁移归档包含：

- SQLite 一致性快照：学生、用户、角色、密码哈希和审计日志
- 服务器运行配置：.env
- 原始 Excel：imports 目录
- 完整 Git 代码包：codemao.git.bundle
- 文件校验和、源提交和学生数量
- 新服务器初始化与恢复脚本

迁移归档包含学生信息和登录密钥，必须按敏感文件管理，不能上传到 GitHub 或公共网盘。

## 当前服务器导出

    cd /opt/codemao
    ./ops/migration-export.sh

默认输出到 /opt/codemao-backups，并保留 30 天。生成 tar.gz 和对应 sha256，两者应一起传输。

仅验证归档，不修改运行服务：

    ./ops/migration-restore.sh --verify-only /opt/codemao-backups/codemao-migration-时间.tar.gz

## 新 Ubuntu 服务器恢复

1. 将迁移 tar.gz 和 sha256 上传到新服务器。
2. 解压归档中的初始化脚本并安装 Docker：

       mkdir -p /tmp/codemao-migration
       tar -xzf /path/codemao-migration-时间.tar.gz -C /tmp/codemao-migration
       /tmp/codemao-migration/bootstrap-ubuntu.sh

   腾讯云且 Docker Hub 访问困难时：

       DOCKER_REGISTRY_MIRROR=https://mirror.ccs.tencentyun.com          /tmp/codemao-migration/bootstrap-ubuntu.sh

3. 重新登录 SSH，使用归档内的 Git bundle 恢复精确代码：

       sudo mkdir -p /opt/codemao
       sudo chown "$USER":"$USER" /opt/codemao
       git clone /tmp/codemao-migration/codemao.git.bundle /opt/codemao

4. 验证并恢复数据：

       cd /opt/codemao
       ./ops/migration-restore.sh --verify-only /path/codemao-migration-时间.tar.gz
       ./ops/migration-restore.sh /path/codemao-migration-时间.tar.gz

5. 浏览器访问新服务器 IP，核对登录、学生总数、姓名查询和 ID 查询。
6. 在云安全组开放 TCP 22 和 80；配置域名和 HTTPS 时再开放 TCP/UDP 443。
7. 在 GitHub 仓库为新服务器添加新的 Deploy Key，更新 origin 后推送/拉取。
8. 新服务器验证完成后再停止旧服务器，至少保留旧服务器 7 天用于回退。

## 自动备份

当前服务器使用 systemd timer 每天约 02:30 创建完整迁移归档：

    systemctl status codemao-migration-backup.timer
    journalctl -u codemao-migration-backup.service
    ls -lh /opt/codemao-backups

修改定时任务后可重新运行：

    ./ops/install-backup-timer.sh

## 恢复验收

迁移完成必须确认：

- docker compose ps 中 app 为 healthy，nginx 为 running
- curl http://127.0.0.1/healthz 返回 ok
- 恢复脚本报告的学生数量与 MANIFEST 一致
- 管理员可以登录，用户与角色权限完整
- 姓名查 ID、ID 查学生和 CSV 导出正常
- Excel 导入记录与审计日志存在
- .env、数据库和迁移归档权限为 600

## 每次项目更新后的异步备份

仓库使用版本化 Git hooks。每次 commit 或 pull/merge 后，都会通过 systemd 异步触发迁移备份，不阻塞 Git 操作。

安装或重新启用：

    cd /opt/codemao
    ./ops/install-backup-timer.sh
    git config --get core.hooksPath

完成应用部署并确认健康后，还必须显式触发一次：

    ./ops/trigger-async-backup.sh post-deploy

确认异步任务执行成功：

    systemctl status codemao-migration-backup.service
    journalctl -u codemao-migration-backup.service -n 50
