# glax_war
AI和人类进行的群星战斗 - Web-based 4X Strategy Game

## 概述
这是一个基于回合制的4X策略游戏（探索-扩张-开发-征服），具有星系地图生成、AI对手、外交系统和声誉机制。

## 功能特性
- **星系地图生成**: 使用网络图算法生成星系
- **回合制游戏**: 玩家和AI轮流行动
- **多种指令**: 殖民、建造、移动、外交、研究
- **AI系统**: 智能AI对手决策
- **资源管理**: 生产、运输、消耗资源
- **外交系统**: 结盟、宣战、贸易
- **声誉机制**: 背叛会影响与其他势力的关系
- **事件日志**: 记录所有游戏事件，支持回放

## 安装

```bash
# 安装依赖
pip install -r requirements.txt

# 运行服务器
python server.py
```

访问 http://localhost:5000 开始游戏

## 游戏规则

### 回合流程
1. 玩家提交指令（殖民/建造/移动/外交/研究）
2. AI决策阶段

## 使用 Docker 快速启动（推荐）

Windows PowerShell 示例：

```powershell
3. 结算引擎执行：
   - 资源产出与运输
   - 建造完成
   - 科研进度
   - 外交关系变化

   - 战斗结算
   - 事件与遗迹效果
```

提示：仓库已忽略 .env 文件，你可以安全地在本机/服务器设置密钥与模型名。

## 战后叙事与 AI 对话

- 战后叙事页：/story
   - 点击页面“生成故事”，会优先调用已配置的 LLM 读取本局编年史生成长文；若 LLM 未启用/无密钥/调用失败，将自动回退到规则式长文，确保不空。
   - 可选写作风格：史诗叙事、纪实口吻、新闻播报。
- 对话创作页：/chat
   - 与 AI 基于“本局编年史”进行多轮对话创作（如重写战史、人物群像、新闻电台稿等）。
   - 支持风格与提供商切换；LLM 不可用时自动回退到规则式摘要/叙事。

相关诊断与素材：
- GET /api/llm/status 查看 LLM 启用状态、提供商、模型、是否有密钥（不返回密钥）。
- GET /api/game/chronicle 导出本局编年史（Markdown）。

## LLM 配置（可选）

通过环境变量控制，支持 Deepseek 与 OpenAI，自动兜底与规则式回退：

- 基础开关
   - LLM_AI_ENABLED=1        开启 LLM 逻辑（默认关闭）
   - LLM_PROVIDER=deepseek|openai  默认优先提供商（可在前端覆盖）
- Deepseek
   - DEEPSEEK_API_KEY=...    必填
   - 可选 DEEPSEEK_API_BASE=https://api.deepseek.com/v1
   - 可选 DEEPSEEK_MODEL=deepseek-chat
- OpenAI
   - OPENAI_API_KEY=...      必填
   - 可选 OPENAI_API_BASE=https://api.openai.com/v1
   - 可选 OPENAI_MODEL=gpt-4o-mini
- 通用回退模型名
   - 可选 LLM_MODEL=...      当未设置各自专属模型名时作为兜底

说明：当首选提供商调用失败且“另一个提供商”存在密钥时，系统会自动再尝试一次；若仍失败，则生成规则式内容作为兜底。

## 安全与提交

- 仓库已包含 `.gitignore`，默认忽略 `.env`、缓存与编辑器文件，避免意外提交密钥。
- 示例文件 `.env.example` 仅提供变量名与注释，请勿在其中填入真实密钥。
4. 记录事件日志

### 资源类型
- **能量**: 用于建造和维护
- **矿物**: 用于建造舰船和建筑
- **科研点**: 用于研究科技

### 胜利条件
- 征服所有星球
- 科技胜利
- 外交胜利

## API接口

### GET /api/game/new
创建新游戏

### GET /api/game/state
获取游戏状态

### POST /api/game/command
提交玩家指令

### POST /api/game/end_turn
结束回合

### GET /api/game/events
获取事件日志

## 技术架构
- **后端**: Python + Flask
- **前端**: HTML + JavaScript + Canvas
- **地图引擎**: NetworkX 图算法
- **数据持久化**: JSON文件（可扩展为数据库）
