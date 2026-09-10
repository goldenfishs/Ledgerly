# 部署、更新与备份

Ledgerly 在一个容器中运行 FastAPI 并提供构建后的 Vue 页面，使用 SQLite 和同目录附件。运行它无需另建数据库或部署 EasyAccounts。

## Docker Compose

在仓库根目录执行：

```sh
cp .env.example .env
docker compose up -d --build
docker compose ps
```

首次访问 [http://localhost:10670](http://localhost:10670) 创建系统管理员。构建过程需要下载 Node.js、Python 基础镜像及依赖；运行普通记账功能无需 AI 或 SMTP 服务。

默认 Compose 项目名为 `ledgerly`，服务名为 `ledgerly`。镜像默认使用 `ghcr.io/goldenfishs/ledgerly:latest`，首次启动配合 `--build` 会在本机构建同名标签；已有发布镜像时可直接拉取。数据卷键为 `ledgerly_data`，默认完整卷名为 `ledgerly_ledgerly_data`；自定义 Compose 项目名会影响实际卷名。容器内数据目录为 `/app/data`，前端目录为 `/app/web`。

常用命令：

```sh
docker compose logs --tail=100 ledgerly
docker compose restart ledgerly
docker compose stop ledgerly
docker compose start ledgerly
```

健康检查接口为 `/api/health`。普通页面返回「前端尚未构建」时，检查是否使用完整多阶段镜像，或在直接运行模式下构建 `frontend/dist/`。

## 端口与团队访问

默认仅绑定 `127.0.0.1:10670`。如端口占用，可在 `.env` 调整：

```dotenv
LEDGERLY_PORT=10672
```

局域网使用时，将 `LEDGERLY_BIND_HOST` 改为服务器可访问的接口地址；`0.0.0.0` 会监听所有 IPv4 接口。根据实际网络设置防火墙和访问范围：

```dotenv
LEDGERLY_BIND_HOST=0.0.0.0
LEDGERLY_PORT=10670
```

修改后运行 `docker compose up -d`。团队应通过同一个可访问地址登录，例如服务器的局域网地址；邀请链接会使用当前页面的地址，不会把 `localhost` 自动转换为服务器地址。

## HTTPS 与反向代理

公网部署应通过 HTTPS 提供服务。可由已有 Nginx、Caddy 或其他反向代理处理 TLS，将请求转发到 Ledgerly。应用及 `/api` 使用同一来源，不需要单独配置跨域 API。

`.env` 示例：

```dotenv
LEDGERLY_BIND_HOST=127.0.0.1
LEDGERLY_PORT=10670
STUDIO_PUBLIC_ORIGIN=https://ledger.example.com
STUDIO_COOKIE_SECURE=true
```

`STUDIO_PUBLIC_ORIGIN` 应与用户浏览器中的协议、域名及端口一致，不包含页面路径。写请求会进行来源校验；通过不同来源提交时会被拒绝。`STUDIO_COOKIE_SECURE=true` 需要实际使用 HTTPS，不能用于普通 HTTP 登录。

反向代理应满足以下要求：

- 保留正确的 `Host`，转发客户端协议与地址信息。
- 将所有应用路径转发给 Ledgerly，包括 `/api`、静态资源和 Vue 页面路由。
- 允许至少 16 MB 的请求体，以覆盖 15 MB 发票及上传表单开销。
- 为发票识别请求保留足够超时，例如 120 秒。

若代理也运行在容器内，代理容器中的 `127.0.0.1` 指向自身，不能用它访问 Ledgerly；需要把两者接入共同 Docker 网络并使用服务名访问。此时应根据自己的代理部署调整网络配置。

首次对外开放前应先在受控访问环境创建系统管理员，再启用团队入口。注册策略和 SMTP 通过系统设置管理，详见[配置说明](configuration.md)。

## 数据目录

完整数据包括：

| 内容 | 用途 |
| --- | --- |
| `studio.sqlite3` 及 SQLite 相关文件 | 用户、会话、账本、流水、发票元信息与系统设置 |
| `invoices/` | 发票原件及预览文件 |
| `avatars/` | 用户头像 |
| `system.key` | SMTP 授权码加密与验证码校验密钥 |

数据库文件名保留兼容名称。不要只备份 CSV 或数据库而遗漏附件和密钥。系统名称、SMTP 配置和注册策略也属于这份数据。

## 备份

为得到数据库与附件一致的快照，可短暂停止服务后复制完整目录。每次使用新的备份目录，避免混入旧文件：

```sh
docker compose stop ledgerly
mkdir -p backups/before-update
docker compose cp ledgerly:/app/data/. backups/before-update/
docker compose start ledgerly
```

确认备份中包含数据库、实际存在的附件目录及 `system.key`。将备份保存到可靠且访问受控的位置；备份含有账号与账务数据，不应提交到 Git 仓库。

## 更新

先备份数据，再拉取代码和重建：

```sh
git pull --ff-only
docker compose up -d --build
docker compose ps
```

检查健康状态、登录、账本列表及一条既有流水或发票。启动时会执行需要的数据库迁移；容器重建不会主动清空数据卷。

新的镜像包含该版本前端资源。更新前请保存正在编辑的表单，更新后刷新页面，避免浏览器继续请求旧版本延迟加载的资源。

也可以在页面左上角打开版本中心。发现 GitHub Release 后，复制其中的更新命令，在部署主机执行；命令会拉取 `ghcr.io/goldenfishs/ledgerly` 的新镜像并重建服务。版本中心只检查发布信息，不在应用容器内执行 Docker 命令。

不要使用 `docker compose down -v` 作为更新步骤，它会删除 Compose 管理的数据卷。若需要回滚，应使用对应的旧代码或镜像以及升级前的完整数据快照，避免让旧程序继续写入已升级数据库。

## 恢复

恢复前先备份当前数据并停止服务。推荐在独立目录与新的 Compose 项目中验证备份，再切换正式服务：

1. 准备与备份匹配的代码或镜像版本，运行 `docker compose create ledgerly` 创建未启动的容器和数据卷。
2. 将完整备份复制到新容器的数据目录：`docker compose cp backups/before-update/. ledgerly:/app/data/`。
3. 将文件所有者设为镜像内运行用户 `10001:10001`，再启动服务：

   ```sh
   docker compose run --rm --no-deps --user 0 --cap-add CHOWN --cap-add DAC_OVERRIDE ledgerly chown -R 10001:10001 /app/data
   docker compose start ledgerly
   ```

4. 验证登录、账本成员、金额、发票原件、头像和邮件配置后，再恢复团队访问。

恢复时应使用空的数据卷，不要将备份覆盖叠加到不同时间的数据目录。遗留的 SQLite WAL 文件或附件可能破坏快照一致性。

## 不使用 Docker

安装 Python 与 Node.js，在仓库根目录执行：

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

此模式打开 [http://localhost:8000](http://localhost:8000)，默认使用仓库的 `data/` 与 `frontend/dist/`。需要其他位置时，通过进程环境设置 `STUDIO_DATA_DIR`、`STUDIO_WEB_DIR`。正式运行应由系统服务管理进程，并按需要配置 HTTPS 反向代理。
