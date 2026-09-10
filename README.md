# 账序 Ledgerly

面向公司与工作室的多用户记账系统。按项目或团队建立账本，邀请同事协作，集中管理收支、资金账户与发票凭证。

Ledgerly 使用 Vue 3、FastAPI 和 SQLite，可通过一个 Docker 服务独立运行，**不需要部署 EasyAccounts、MySQL 或其他 AI 服务容器**。发票 AI 识别为可选功能，未配置时仍能上传原件并手工核对。

## 功能

| 模块 | 功能 |
| --- | --- |
| 多账本协作 | 创建与切换账本，每个账本分别管理成员、角色和邀请 |
| 收支与账户 | 收入、支出、转账、待审核记录、资产及负债账户 |
| 报表与日志 | 按账本和权限统计已审核收支，查看操作记录 |
| 发票凭证 | 图片及 PDF 上传、预览、可选 AI 识别、人工核对、回收站恢复 |
| 个人中心 | 修改账号与密码、上传头像、验证邮箱、通过邮箱找回密码 |
| 系统管理 | 系统名称、开放或邀请注册、关闭注册、强制邮箱验证与 SMTP 配置 |

界面采用清爽浅色与柔和彩色卡片，支持桌面与手机布局。当前记账币种为人民币，金额以整数分存储。

## 快速启动

需要安装 Docker Engine 和 Docker Compose。

```sh
git clone https://github.com/goldenfishs/Ledgerly.git
cd Ledgerly
cp .env.example .env
docker compose up -d --build
```

打开 [http://localhost:10670](http://localhost:10670)。首次访问时创建工作区、系统管理员和第一个账本；没有预置账号或默认密码。

若 10670 端口已被占用，在 `.env` 中修改 `LEDGERLY_PORT`，然后重新启动。例如：

```dotenv
LEDGERLY_PORT=10672
```

Docker 构建会安装依赖并打包前端，无需在宿主机安装 Node.js 或 Python。数据保存在独立命名卷中，重建容器后仍然保留。

默认仅允许本机访问。团队跨设备使用时，请按照[部署说明](docs/deployment.md)设置可共同访问的地址；其他电脑无法通过你复制的 `localhost` 邀请链接访问服务。

点击左侧的「账序 Ledgerly」可以打开版本中心。它会检查 GitHub Releases；发现新版本时显示发布说明和 GHCR 镜像更新命令。应用容器不会挂载 Docker Socket，更新命令需要在部署主机上执行，避免网页账号直接控制宿主机 Docker。

## 从第一笔账开始

1. 在「资金账户」建立银行账户、备用金或负债账户，填写期初余额。
2. 在「账本成员」创建邀请，选择成员或账本管理员角色。同事通过链接登录或注册并加入。
3. 在「收支流水」录入收入、支出或转账，交由账本管理员审核。
4. 在「发票凭证」上传原件并核对信息；发票与流水分别管理，上传凭证不会自动生成流水。
5. 根据团队需要，在「系统设置」配置注册方式与邮件服务。

新流水进入待审核状态，只有已审核记录影响余额和统计。转账影响双方账户余额，不计入收入或支出。系统用于记账管理，不连接银行或执行付款。

## 权限如何分配

| 角色 | 可操作范围 |
| --- | --- |
| 系统管理员 | 创建账本，管理全站注册方式、系统名称与邮件服务 |
| 账本管理员 | 管理已加入账本的账户、分类、成员、审核及日志，查看该账本全部流水与发票 |
| 账本成员 | 查看和处理该账本中本人提交的流水与发票，不能查看团队账户余额 |

系统管理员不会自动获得所有账本的数据权限。一个账号可以在不同账本拥有不同角色；未加入任何账本时，仍能使用个人中心并接受邀请。

每条邀请只能使用一次，支持到期与撤销。默认采用「仅邀请注册」；开放注册产生的普通账号不会自动加入账本，也不会获得系统管理权限。具体规则见[配置说明](docs/configuration.md)。

## 开发

推荐使用 Python 3.12 与 Node.js 22。在仓库根目录创建虚拟环境并启动后端：

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Windows PowerShell 使用 `.venv\Scripts\Activate.ps1` 激活环境。另开终端启动前端：

```sh
npm ci --prefix frontend
npm run dev --prefix frontend
```

打开 Vite 输出的地址。前端开发服务器将 `/api` 代理到本机 8000；开发数据默认写入仓库下的 `data/`。若修改后端端口，可通过启动前端时的 `LEDGERLY_API_PROXY` 环境变量同步调整代理地址，避免请求其他正在运行的实例。

## 项目结构

```text
backend/          FastAPI、权限、账务、发票及身份服务
frontend/         Vue 3 页面与组件
tests/            自动化测试，使用临时数据和模拟外部服务
docs/             配置、部署与验证说明
compose.yaml      独立 Docker 服务
Dockerfile        前端构建与后端运行镜像
```

运行检查：

```sh
python -m pytest -q
node --test tests/test_frontend.mjs
npm run format:check --prefix frontend
npm run build --prefix frontend
```

验证范围、浏览器检查清单与结果说明见[验证文档](docs/verification.md)。贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 文档

- [系统、注册、SMTP 与发票识别配置](docs/configuration.md)
- [部署、更新、备份与恢复](docs/deployment.md)
- [测试与浏览器验证](docs/verification.md)

## 许可证与致谢

采用 [MIT License](LICENSE)。保留原始许可证中的版权声明。

Ledgerly 的记账概念与早期实现源自 [EasyAccounts 上游](https://github.com/QingHeYang/EasyAccounts)，以 [goldenfishs/EasyAccounts](https://github.com/goldenfishs/EasyAccounts) 的本地扩展为开发起点，整理为独立的公司与工作室协作记账项目。出处见 [NOTICE](NOTICE)。感谢原项目及开源依赖的贡献者。
