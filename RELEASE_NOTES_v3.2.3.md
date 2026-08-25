# 橘味儿音乐 v3.2.3

## 本次更新

- 修复服务器曲库任务提交后卡在 8% 并返回 HTTP 404 的问题；任务查询与产物下载统一走曲库 API 路由。
- 服务器歌曲执行 AI 处理前显示确认说明，提交后明确提示已加入队列并可跳转流水线。
- 音乐库改为歌手头像、推荐歌手、A-Z 索引和歌手详情列表，更适合手机端浏览 1 万首以上曲库。
- App 改为注册或登录后才可进入；支持自选账号或手机号登录。
- 注册必须绑定中国大陆手机号；短信验证码 60 秒内限发一次、5 分钟有效。
- 新增手机号验证码找回密码。
- 新增个人设置：头像、昵称、性别、个人简介、籍贯、住址和微信号。
- 内测群聊保持登录鉴权，仅登录用户可读取和发送消息。
- 阿里云短信凭据仅从服务器环境变量读取，不写入源码、客户端或安装包。

## 服务器部署

服务器需配置以下环境变量后重启 Mobile API：

```text
ALIBABA_CLOUD_ACCESS_KEY_ID
ALIBABA_CLOUD_ACCESS_KEY_SECRET
ALIYUN_SMS_SIGN_NAME
ALIYUN_SMS_TEMPLATE_CODE
ADMIN_KEY
JUWEIER_SERVER_LIBRARY
```

曲库 Cloudflare 路由继续使用 `/api/v1/library*` 指向 Mobile API 服务。
