"""
Flask服务器
提供REST API接口
"""
from flask import Flask, jsonify, request, send_from_directory
# 可选依赖：flask_cors、python-dotenv；本地未安装时提供降级实现，避免导入错误
try:
    from flask_cors import CORS  # type: ignore
except Exception:  # pragma: no cover - fallback for environments without flask_cors
    def CORS(app, *args, **kwargs):
        return app
import os
import random
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover - fallback for environments without python-dotenv
    def load_dotenv(*args, **kwargs):
        return False
import time

from game_engine import (
    Faction, Resources, Command, CommandType,
    Technology, Fleet, ShipType, DiplomacyStatus
)
from galaxy_generator import GalaxyGenerator
from ai_system import AISystem
from turn_engine import TurnEngine
from llm_agent import generate_story_from_chronicle, generate_rule_based_story, chat_reply
# 调试用途：读取 LLM 配置状态（注意不返回密钥本身）
from llm_agent import _is_enabled as _llm_enabled  # type: ignore
from llm_agent import _api_config as _llm_api_config  # type: ignore


app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# 全局游戏状态
game_state = None
galaxy_gen = None
ai_system = None
turn_engine = None


def _get_assault_always_factions():
    """停战结束后，计算当前舰队数量最多的势力（可并列）。
    满足条件的势力拥有“持续强袭”权限：即便仍拥有行星，也可使用强袭。
    返回值：set([faction_id, ...])
    """
    if game_state is None:
        return set()
    # 停战未结束则无特权
    try:
        if getattr(game_state, 'truce_until', 0) and time.time() < game_state.truce_until:
            return set()
    except Exception:
        return set()
    # 统计各势力的“舰队总数”（对象个数）
    fleet_counts = {}
    for fid, f in game_state.factions.items():
        fleet_counts[fid] = len(f.fleets or [])
    if not fleet_counts:
        return set()
    max_cnt = max(fleet_counts.values())
    if max_cnt <= 0:
        return set()
    leaders = {fid for fid, c in fleet_counts.items() if c == max_cnt}
    return leaders


def initialize_game(num_planets=30, num_ai=3, max_turns: int = 200,
                    victory_config: dict | None = None,
                    truce_seconds: int = 300,
                    clustered: bool = True,
                    player_name: str | None = None):
    """初始化游戏"""
    global game_state, galaxy_gen, ai_system, turn_engine
    
    # 生成星系（默认按簇生成：每个势力一片起始区域）
    galaxy_gen = GalaxyGenerator(num_planets=num_planets, seed=random.randint(1, 10000))
    if clustered:
        game_state = galaxy_gen.generate_clustered(num_ai + 1)
    else:
        game_state = galaxy_gen.generate()
    
    # 创建科技树
    _initialize_technologies()
    
    # 创建势力
    _initialize_factions(num_ai, cluster_labels=getattr(galaxy_gen, 'cluster_labels', None), player_name=player_name)
    
    # 初始化AI和回合引擎
    ai_system = AISystem(game_state, galaxy_gen)
    turn_engine = TurnEngine(game_state, galaxy_gen)
    
    # 设置最大回合并记录开始事件
    game_state.max_turns = max_turns
    if victory_config:
        # 仅合并允许的键
        allowed = set(game_state.victory_config.keys())
        for k, v in victory_config.items():
            if k in allowed:
                game_state.victory_config[k] = v
    # 强制关闭科技胜与经济胜，按“综合评价”终局
    game_state.victory_config['tech_victory_enabled'] = False
    game_state.victory_config['econ_victory_enabled'] = False
    # 停战设置
    now = time.time()
    game_state.game_start_time = now
    game_state.truce_until = (now + truce_seconds) if truce_seconds and truce_seconds > 0 else 0.0
    truce_msg = f"停战 {truce_seconds//60} 分钟" if game_state.truce_until > 0 else "无停战"
    game_state.add_event("game_start", None, f"游戏开始！回合上限 {game_state.max_turns}，{truce_msg}")
    
    return game_state


def _initialize_technologies():
    """初始化科技树"""
    technologies = [
        Technology("tech_laser", "激光武器", 100.0),
        Technology("tech_shields", "能量护盾", 1700.0),
        Technology("tech_ftl", "超光速引擎", 200.0),
        Technology("tech_colonization", "殖民技术", 120.0),
        Technology("tech_mining", "高级采矿", 130.0),
        Technology("tech_power", "聚变能源", 140.0),
    ]
    
    for tech in technologies:
        game_state.technologies[tech.id] = tech


def _initialize_factions(num_ai, cluster_labels=None, player_name: str | None = None):
    """初始化势力"""
    # 创建玩家势力
    player = Faction(
        id="player",
        name=(player_name or "人类联邦"),
        is_ai=False,
        resources=Resources(energy=500, minerals=500, research=100)
    )
    game_state.factions[player.id] = player
    
    # 创建AI势力
    # 随机生成 AI 势力名称
    ai_prefix = ["天琴", "猎户", "仙女", "银河", "新星", "星环", "曙光", "长风", "烁星", "雷霆", "曦光", "空庭"]
    ai_suffix = ["帝国", "共和国", "联邦", "公国", "议会", "联盟", "邦联", "自治领", "财团", "教团"]
    used = set()
    def gen_name(idx: int) -> str:
        for _ in range(10):
            n = f"{random.choice(ai_prefix)}{random.choice(ai_suffix)}"
            if n not in used:
                used.add(n)
                return n
        return f"星际势力{idx}"
    for i in range(num_ai):
        ai_faction = Faction(
            id=f"ai_{i}",
            name=gen_name(i),
            is_ai=True,
            resources=Resources(energy=500, minerals=500, research=100)
        )
        game_state.factions[ai_faction.id] = ai_faction
    
    # 为每个势力分配起始星球（优先使用不同簇）
    factions_order = list(game_state.factions.values())
    if cluster_labels:
        # 计算各簇中心
        cluster_ids = sorted(set(cluster_labels.values()))
        cluster_to_planets = {cid: [pid for pid, c in cluster_labels.items() if c == cid] for cid in cluster_ids}
        # 计算簇质心
        cluster_centers = {}
        for cid, pids in cluster_to_planets.items():
            if not pids:
                continue
            sx = sy = 0.0
            for pid in pids:
                p = game_state.planets[pid]
                sx += p.position[0]
                sy += p.position[1]
            cluster_centers[cid] = (sx/len(pids), sy/len(pids))

        def dist2pos(pos, center):
            dx = pos[0] - center[0]
            dy = pos[1] - center[1]
            return dx*dx + dy*dy

        used_planets = set()
        for idx, faction in enumerate(factions_order):
            cid = cluster_ids[idx % len(cluster_ids)]
            center = cluster_centers.get(cid, (0.0, 0.0))
            candidates = [pid for pid in cluster_to_planets.get(cid, []) if pid not in used_planets]
            if not candidates:
                # 退化到全局可用
                candidates = [pid for pid in game_state.planets.keys() if pid not in used_planets]
            # 选离簇中心最近的作为起点
            start_planet_id = min(candidates, key=lambda pid: dist2pos(game_state.planets[pid].position, center)) if candidates else None
            if not start_planet_id:
                continue
            used_planets.add(start_planet_id)
            start_planet = game_state.planets[start_planet_id]
            start_planet.owner = faction.id
            start_planet.population = 100
            faction.planets.append(start_planet_id)

            # 创建初始舰队
            fleet = Fleet(
                id=f"fleet_{faction.id}_0",
                owner=faction.id,
                ships={ShipType.CORVETTE: 3, ShipType.SCOUT: 5},
                position=start_planet_id
            )
            game_state.fleets[fleet.id] = fleet
            faction.fleets.append(fleet.id)
    else:
        # 随机分配（旧逻辑）
        available_planets = list(game_state.planets.keys())
        random.shuffle(available_planets)
        for i, faction in enumerate(factions_order):
            if i >= len(available_planets):
                break
            start_planet_id = available_planets[i]
            start_planet = game_state.planets[start_planet_id]
            start_planet.owner = faction.id
            start_planet.population = 100
            faction.planets.append(start_planet_id)

            # 创建初始舰队
            fleet = Fleet(
                id=f"fleet_{faction.id}_0",
                owner=faction.id,
                ships={ShipType.CORVETTE: 3, ShipType.SCOUT: 5},
                position=start_planet_id
            )
            game_state.fleets[fleet.id] = fleet
            faction.fleets.append(fleet.id)
    
    # 初始化外交关系
    faction_ids = list(game_state.factions.keys())
    for faction_id in faction_ids:
        faction = game_state.factions[faction_id]
        for other_id in faction_ids:
            if other_id != faction_id:
                faction.diplomacy[other_id] = DiplomacyStatus.NEUTRAL


@app.route('/')
def index():
    """首页"""
    return send_from_directory('static', 'index.html')


@app.route('/api/game/new', methods=['GET'])
def new_game():
    """创建新游戏"""
    num_planets = int(request.args.get('planets', 30))
    num_ai = int(request.args.get('ai', 3))
    max_turns = int(request.args.get('max_turns', 200))
    truce_seconds = int(request.args.get('truce_seconds', 300))
    clustered = request.args.get('clustered', '1') not in ('0', 'false', 'False')
    player_name = request.args.get('player_name')

    # 胜利条件配置（通过 query 简单传参）
    # 示例：&tech_victory=1&tech_ids=tech_ftl,tech_power&econ_victory=1&econ_window=3&econ_threshold=200
    vcfg = {}
    if request.args.get('tech_victory'):
        vcfg['tech_victory_enabled'] = True
    tech_ids = request.args.get('tech_ids')
    if tech_ids:
        vcfg['tech_required_ids'] = [s.strip() for s in tech_ids.split(',') if s.strip()]
    tech_threshold = request.args.get('tech_threshold')
    if tech_threshold:
        try:
            vcfg['tech_score_threshold'] = float(tech_threshold)
        except Exception:
            pass
    if request.args.get('econ_victory'):
        vcfg['econ_victory_enabled'] = True
    econ_window = request.args.get('econ_window')
    if econ_window:
        try:
            vcfg['econ_window'] = int(econ_window)
        except Exception:
            pass
    econ_threshold = request.args.get('econ_threshold')
    if econ_threshold:
        try:
            vcfg['econ_threshold'] = float(econ_threshold)
        except Exception:
            pass

    state = initialize_game(num_planets, num_ai, max_turns, vcfg or None, truce_seconds, clustered, player_name)
    
    return jsonify({
        "success": True,
        "message": "游戏创建成功",
        "game_state": state.to_dict()
    })


@app.route('/api/game/state', methods=['GET'])
def get_state():
    """获取游戏状态"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    
    return jsonify({
        "success": True,
        "game_state": game_state.to_dict()
    })


@app.route('/api/game/rules', methods=['GET'])
def get_rules_doc():
    """返回一份简明规则说明给前端展示。"""
    rules = {
        "core": [
            "资源产出来源于已占领星球与建筑（能量/矿物/科研）",
            "每回合自动推进：人口增长、建造、研究、移动、战斗、外交",
            "胜利以综合评价为准：回合上限或一统/淘汰后比综合实力",
        ],
        "combat": [
            "停战期内不触发战斗与占领；结束后开放",
            "强袭成功率=进攻/防御有效战力对比（含熟练/科技/邻接/防御/围攻/滩头保护）",
            "围攻失败会累计围攻点数，使防御系数随次数衰减；成功占领后清零",
            "滩头保护：星球被夺后2回合内防御额外×1.2，避免立刻被反抢",
            "防御模式与防御站/科技/护盾可拦截强袭",
        ],
        "assault": [
            "背城一击：当势力无行星，且在某星球集结舰船艘数>阈值（默认>10）可尝试强袭",
            "强袭特权：停战结束后，舰队数量最多的势力（可并列）无论是否有行星均可强袭",
        ],
        "alloc": [
            "每星球驻军有上限（基础5，每船坞+2），可为己方自定义更低的分派上限",
            "连线巡逻可拦截跨越该边的敌舰，概率≈Σ(巡逻战力)×0.02，最多100%",
        ],
        "llm": [
            "可选 LLM 决策：玩家侧默认使用 OpenAI（若配置），AI 侧默认 Deepseek（若配置）",
            "未配置或出错时自动回退到规则式AI，不影响游戏进行",
        ]
    }
    return jsonify({"success": True, "rules": rules})


@app.route('/api/game/narrative', methods=['GET'])
def get_narrative():
    """基于编年史与历史评分，生成战后叙事（不依赖外部API）。"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    # 收集素材
    lines = []
    lines.append(f"战后回顾：第 {game_state.turn} 回合")
    try:
        # 胜负摘要
        if game_state.game_over:
            wname = game_state.factions.get(game_state.winner).name if game_state.winner in game_state.factions else (game_state.winner or '-')
            lines.append(f"结局：{wname} 获胜（{game_state.end_reason or '综合实力领先'}）")
        # 关键事件（近40条）
        import time as _t
        important = []
        for ev in game_state.events[-120:]:
            if ev.event_type in {"planet_conquered","planet_captured","defense_success","combat","research_completed","colonization"}:
                ts = _t.strftime('%H:%M:%S', _t.localtime(ev.timestamp))
                fname = game_state.factions.get(ev.faction).name if ev.faction in game_state.factions else (ev.faction or '-')
                important.append(f"[回合{ev.turn} {ts}] {fname}: {ev.description}")
        if important:
            lines.append("关键战报：")
            lines.extend(["- "+s for s in important[-40:]])
        # 势力走势
        if getattr(game_state, 'power_history', None):
            last_snap = game_state.power_history[-1]
            ranking = sorted(last_snap.items(), key=lambda kv: kv[1], reverse=True)
            lines.append("终局实力排行：")
            for fid, sc in ranking:
                nm = game_state.factions.get(fid).name if fid in game_state.factions else fid
                lines.append(f"- {nm}: {sc:.1f}")
    except Exception:
        pass
    return jsonify({"success": True, "narrative": "\n".join(lines)})


@app.route('/api/game/story', methods=['POST'])
def generate_story():
    """生成战后长篇叙事（LLM），body: { style?: 'epic'|'documentary'|'news', provider?: 'openai'|'deepseek' }
    若LLM未启用或无密钥，返回 success:true, story:''。
    """
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    style = data.get('style')
    provider = data.get('provider')  # 可选，若不传则按各自默认
    # 默认策略：若传 provider 则用该 provider，否则根据是否有 OPENAI/DEEPSEEK 由 LLM 模块自行判定
    story = generate_story_from_chronicle(game_state, style=style, provider_override=provider)
    # 若生成失败/为空，返回更明确的原因，便于客户端提示
    if not story:
        prov = (provider or os.getenv('LLM_PROVIDER') or 'deepseek')
        cfg = _llm_api_config(provider)
        enabled = _llm_enabled()
        has_key = bool(cfg.get('key'))
        msg = 'LLM 未启用'
        if enabled and not has_key:
            msg = f"{prov} 未配置密钥"
        elif enabled and has_key:
            msg = f"{prov} 调用失败或返回空内容（可能是网络/权限/模型名问题）"
        # 本地规则兜底
        fallback = generate_rule_based_story(game_state, style=style)
        return jsonify({"success": True, "story": fallback, "message": msg, "provider": prov, "enabled": enabled, "fallback": True})
    return jsonify({"success": True, "story": story})


@app.route('/api/llm/status', methods=['GET'])
def llm_status():
    """返回 LLM 配置状态：是否启用、提供商、模型名、是否存在密钥（不回传密钥）。"""
    try:
        prov = (request.args.get('provider') or os.getenv('LLM_PROVIDER') or 'deepseek')
        # 当传入 provider 名称时，_llm_api_config 期望的是覆盖参数
        cfg = _llm_api_config(prov)
        return jsonify({
            "success": True,
            "enabled": _llm_enabled(),
            "provider": (prov or '').lower(),
            "model": cfg.get('model'),
            "has_key": bool(cfg.get('key'))
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/chat', methods=['POST'])
def chat_api():
    """对话接口：接受 { user_text, style?, provider?, history? } 返回 { reply }。"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    user_text = (data.get('user_text') or '').strip()
    style = data.get('style')
    provider = data.get('provider')
    history = data.get('history') if isinstance(data.get('history'), list) else None
    if not user_text:
        return jsonify({"success": False, "message": "缺少 user_text"}), 400
    try:
        reply = chat_reply(game_state, user_text=user_text, history=history, style=style, provider_override=provider)
        return jsonify({"success": True, "reply": reply})
    except Exception as e:
        # 兜底：返回规则式首段
        fb = generate_rule_based_story(game_state, style=style).split('\n\n')[0]
        return jsonify({"success": True, "reply": fb, "message": str(e), "fallback": True})


@app.route('/story', methods=['GET'])
def story_page():
    """叙事页面：用于在前端点击“结算/生成故事”后跳转展示。"""
    return send_from_directory('static', 'story.html')


@app.route('/chat', methods=['GET'])
def chat_page():
    """对话页面：用于与 AI 进行历史共创对话。"""
    return send_from_directory('static', 'chat.html')


@app.route('/api/game/chronicle', methods=['GET'])
def export_chronicle():
    """导出本局编年史（Markdown）。"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    # 头部
    lines = []
    lines.append(f"# 星际编年史：第 {game_state.turn} 回合")
    lines.append("")
    # 势力列表
    lines.append("## 势力名录")
    for f in game_state.factions.values():
        lines.append(f"- {f.name}（ID: {f.id}） 行星 {len(f.planets)}，舰队 {len(f.fleets)}，声誉 {int(f.reputation)}")
    lines.append("")
    # 按时间排序事件
    lines.append("## 大事记")
    sorted_events = sorted(game_state.events, key=lambda e: (e.turn, e.timestamp))
    for ev in sorted_events:
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ev.timestamp))
        who = game_state.factions.get(ev.faction).name if ev.faction in (game_state.factions or {}) else (ev.faction or "-")
        lines.append(f"- 回合 {ev.turn}（{ts}）[{ev.event_type}] {who}: {ev.description}")
    lines.append("")
    # 每回合评分快照
    if getattr(game_state, 'power_history', None):
        lines.append("## 每回合综合评分快照")
        for idx, snap in enumerate(game_state.power_history, start=1):
            pretty = ", ".join([f"{game_state.factions.get(fid).name if fid in game_state.factions else fid}: {score:.1f}" for fid, score in snap.items()])
            lines.append(f"- 回合 {idx}: {pretty}")
        lines.append("")

    # 势力疆域快照（JSON 行，便于后续外部渲染）
    try:
        terr = {pid: (p.owner or "-") for pid, p in game_state.planets.items()}
        lines.append("## 势力疆域（JSON 快照）")
        import json as _json
        lines.append("```json")
        lines.append(_json.dumps(terr, ensure_ascii=False))
        lines.append("```")
        lines.append("")
    except Exception:
        pass

    # 结算/比分
    if game_state.game_over:
        lines.append("## 最终结算")
        lines.append(f"- 胜者：{game_state.factions.get(game_state.winner).name if game_state.winner in game_state.factions else game_state.winner}")
        lines.append(f"- 原因：{game_state.end_reason}")
        lines.append("")
        if getattr(game_state, 'final_scores', None):
            lines.append("### 综合评分")
            for fid, score in sorted(game_state.final_scores.items(), key=lambda kv: kv[1], reverse=True):
                nm = game_state.factions.get(fid).name if fid in game_state.factions else fid
                lines.append(f"- {nm}: {score:.1f}")
    md = "\n".join(lines)
    return jsonify({"success": True, "markdown": md})


@app.route('/api/game/command', methods=['POST'])
def submit_command():
    """提交玩家指令"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    
    data = request.json
    try:
        command = Command(
            faction_id=data.get('faction_id', 'player'),
            command_type=CommandType(data['command_type']),
            parameters=data['parameters']
        )
        
        game_state.pending_commands.append(command)
        
        return jsonify({
            "success": True,
            "message": "指令已提交"
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400


@app.route('/api/game/end_turn', methods=['POST'])
def end_turn():
    """结束回合"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    
    if getattr(game_state, 'game_over', False):
        return jsonify({
            "success": True,
            "message": "游戏已结束，不能继续结束回合",
            "game_state": game_state.to_dict()
        })

    try:
        # 收集AI指令
        for faction_id, faction in game_state.factions.items():
            if faction.is_ai:
                ai_commands = ai_system.generate_ai_commands(faction_id)
                game_state.pending_commands.extend(ai_commands)
        
        # 处理回合
        turn_engine.process_turn(game_state.pending_commands)
        
        # 清空待处理指令
        game_state.pending_commands = []
        
        return jsonify({
            "success": True,
            "message": f"第 {game_state.turn} 回合结束",
            "game_state": game_state.to_dict()
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400


@app.route('/api/game/events', methods=['GET'])
def get_events():
    """获取事件日志"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    
    limit = int(request.args.get('limit', 50))
    events = [e.to_dict() for e in game_state.events[-limit:]]
    
    return jsonify({
        "success": True,
        "events": events
    })


@app.route('/api/game/planet/<planet_id>', methods=['GET'])
def get_planet_details(planet_id):
    """获取星球详情"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    
    planet = game_state.planets.get(planet_id)
    if not planet:
        return jsonify({"success": False, "message": "星球不存在"}), 404
    
    # 获取连接的星球
    connected = galaxy_gen.get_connected_planets(game_state, planet_id)
    
    # 统计该星球“各势力舰船艘数”与“己方（玩家）在此的艘数”
    ships_per_faction = {}
    for fl in game_state.fleets.values():
        if fl.position == planet_id and fl.owner:
            ships_per_faction[fl.owner] = ships_per_faction.get(fl.owner, 0) + sum((fl.ships or {}).values())
    player_count = ships_per_faction.get('player', 0)
    threshold = int(getattr(game_state, 'rules', {}).get('desperate_capture_threshold', 10))
    assault_always = _get_assault_always_factions()
    assault_always_player = ('player' in assault_always)

    return jsonify({
        "success": True,
        "planet": planet.to_dict(),
        "connected_planets": connected,
        "ship_counts": ships_per_faction,
        "player_ship_count": player_count,
    "desperate_threshold": threshold,
    "assault_always_player": assault_always_player
    })


@app.route('/api/planet/assault', methods=['POST'])
def assault_planet():
    """背城一击：当某势力无行星时，若在某星球集结舰船总数超过阈值，可尝试强袭占领。
    body: { planet_id, faction_id }
    成功与否依照 TurnEngine._attempt_planet_capture 的规则（包括停战/护盾判定）。
    """
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    pid = data.get('planet_id')
    fid = data.get('faction_id', 'player')
    if pid not in game_state.planets:
        return jsonify({"success": False, "message": "星球不存在"}), 404
    if fid not in game_state.factions:
        return jsonify({"success": False, "message": "势力不存在"}), 404
    planet = game_state.planets[pid]
    attacker = game_state.factions[fid]
    # 判断是否具备强袭资格：
    # 1) 原规则：当势力无行星时；
    # 2) 新增：停战结束后，舰队数量最多的势力（可并列）拥有“持续强袭”权限。
    assault_allowed = False
    if len(attacker.planets) == 0:
        assault_allowed = True
    else:
        leaders = _get_assault_always_factions()
        if fid in leaders:
            assault_allowed = True
    if not assault_allowed:
        return jsonify({"success": False, "message": "当前不满足强袭条件（需无行星或拥有持续强袭特权）"}), 400
    if not planet.owner:
        return jsonify({"success": False, "message": "目标星球无主，无需强袭"}), 400
    defender = game_state.factions.get(planet.owner)
    # 计算己方在此的舰数
    ships_here = 0
    for fl in game_state.fleets.values():
        if fl.owner == attacker.id and fl.position == pid:
            try:
                ships_here += sum(int(v) for v in (fl.ships or {}).values())
            except Exception:
                for v in (fl.ships or {}).values():
                    try:
                        ships_here += int(v)
                    except Exception:
                        pass
    threshold = int(getattr(game_state, 'rules', {}).get('desperate_capture_threshold', 10))
    if ships_here <= threshold:
        return jsonify({"success": False, "message": f"舰船不足（>{threshold} 艘）"}), 400
    # 调用现有逻辑尝试占领
    ok = False
    capture_details = None
    try:
        # 先计算一次详情供返回
        beachhead_mult = 1.0
        try:
            if getattr(planet, 'capture_protection_until_turn', 0) and game_state.turn < planet.capture_protection_until_turn:
                beachhead_mult = 1.2
        except Exception:
            pass
        atk_p, def_p, details = turn_engine._calc_capture_effective_power(attacker, defender, planet, beachhead_mult)  # type: ignore
        # 计算成功概率
        alpha = 1.1
        try:
            a = max(0.0, atk_p) ** alpha
            d = max(0.0, def_p) ** alpha
            prob = (a / (a + d)) if (a + d) > 0 else 0.0
        except Exception:
            prob = 0.0
        capture_details = {"attack_power": atk_p, "defense_power": def_p, "prob": prob, "factors": details}
        # 实际尝试占领
        ok = turn_engine._attempt_planet_capture(attacker, defender, planet)  # type: ignore
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    if ok:
        return jsonify({"success": True, "message": "强袭成功", "game_state": game_state.to_dict(), "capture": capture_details})
    return jsonify({"success": False, "message": "强袭未果（可能被防御/停战阻止）", "capture": capture_details}), 200


@app.route('/api/planet/assault_preview', methods=['GET'])
def assault_preview():
    """强袭预览：返回当前条件下的强袭资格、阈值预检与成功率估算。
    query: planet_id, faction_id=player
    """
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    pid = request.args.get('planet_id')
    fid = request.args.get('faction_id', 'player')
    if not pid or pid not in game_state.planets:
        return jsonify({"success": False, "message": "星球不存在"}), 404
    if fid not in game_state.factions:
        return jsonify({"success": False, "message": "势力不存在"}), 404
    planet = game_state.planets[pid]
    defender = game_state.factions.get(planet.owner) if planet.owner else None
    attacker = game_state.factions[fid]
    # 资格判断
    leaders = _get_assault_always_factions()
    qualified = (len(attacker.planets) == 0) or (fid in leaders)
    # 舰船阈值
    ships_here = 0
    for fl in game_state.fleets.values():
        if fl.owner == attacker.id and fl.position == pid:
            try:
                ships_here += sum(int(v) for v in (fl.ships or {}).values())
            except Exception:
                for v in (fl.ships or {}).values():
                    try:
                        ships_here += int(v)
                    except Exception:
                        pass
    threshold = int(getattr(game_state, 'rules', {}).get('desperate_capture_threshold', 10))
    # 仅当有防守方时计算有效战力
    capture = None
    if defender is not None:
        beachhead_mult = 1.0
        try:
            if getattr(planet, 'capture_protection_until_turn', 0) and game_state.turn < planet.capture_protection_until_turn:
                beachhead_mult = 1.2
        except Exception:
            pass
        try:
            atk_p, def_p, details = turn_engine._calc_capture_effective_power(attacker, defender, planet, beachhead_mult)  # type: ignore
            alpha = 1.1
            a = max(0.0, atk_p) ** alpha
            d = max(0.0, def_p) ** alpha
            prob = (a / (a + d)) if (a + d) > 0 else 0.0
            capture = {"attack_power": atk_p, "defense_power": def_p, "prob": prob, "factors": details}
        except Exception:
            pass
    return jsonify({
        "success": True,
        "qualified": qualified,
        "assault_always": (fid in leaders),
        "ships_here": ships_here,
        "threshold": threshold,
        "defender": (defender.id if defender else None),
        "capture": capture
    })


@app.route('/api/game/faction/<faction_id>', methods=['GET'])
def get_faction_details(faction_id):
    """获取势力详情"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    
    faction = game_state.factions.get(faction_id)
    if not faction:
        return jsonify({"success": False, "message": "势力不存在"}), 404
    
    return jsonify({
        "success": True,
        "faction": faction.to_dict()
    })


@app.route('/api/fleets', methods=['GET'])
def list_fleets():
    """列出所有舰队或指定势力舰队 (?owner=faction_id)"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    owner = request.args.get('owner')
    fleets = []
    for fid, f in game_state.fleets.items():
        if owner and f.owner != owner:
            continue
        fleets.append(f.to_dict())
    return jsonify({"success": True, "fleets": fleets})


@app.route('/api/fleet/create', methods=['POST'])
def create_fleet():
    """在某个己方星球创建舰队，初始从该星球驻军/势力资源中转入舰船。
    body: { owner, planet_id, ships: {scout?:n, corvette?:n, destroyer?:n, cruiser?:n, battleship?:n} }
    资源规则：每艘船扣矿与能量（简化）：
      侦察1/3；护卫3/6；驱逐8/12；巡洋20/30；战列50/80（矿/能）。
    """
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    owner = data.get('owner', 'player')
    planet_id = data.get('planet_id')
    ships_req = data.get('ships') or {}
    if owner not in game_state.factions:
        return jsonify({"success": False, "message": "势力不存在"}), 400
    if planet_id not in game_state.planets:
        return jsonify({"success": False, "message": "星球不存在"}), 400
    planet = game_state.planets[planet_id]
    if planet.owner != owner:
        return jsonify({"success": False, "message": "只能在己方星球创建舰队"}), 400

    faction = game_state.factions[owner]
    cost_table = {
        'scout': (1, 3), 'corvette': (3, 6), 'destroyer': (8, 12), 'cruiser': (20, 30), 'battleship': (50, 80)
    }
    need_min = 0.0
    need_en = 0.0
    for k, v in ships_req.items():
        v = int(v or 0)
        if v <= 0 or k not in cost_table:
            continue
        m, e = cost_table[k]
        need_min += m * v
        need_en += e * v
    if faction.resources.minerals < need_min or faction.resources.energy < need_en:
        return jsonify({"success": False, "message": "资源不足"}), 400
    # 扣费
    faction.resources.minerals -= need_min
    faction.resources.energy -= need_en

    # 组装舰队
    ships = {}
    map_type = {
        'scout': ShipType.SCOUT, 'corvette': ShipType.CORVETTE, 'destroyer': ShipType.DESTROYER,
        'cruiser': ShipType.CRUISER, 'battleship': ShipType.BATTLESHIP
    }
    for k, v in ships_req.items():
        v = int(v or 0)
        if v > 0 and k in map_type:
            ships[map_type[k]] = v

    # 驻扎上限：同一星球最多5支舰队
    stationed = sum(1 for f in game_state.fleets.values() if f.position == planet_id)
    if stationed >= 5:
        return jsonify({"success": False, "message": "该星球驻扎舰队已达上限(5)"}), 400

    new_id = f"fleet_{owner}_{len(game_state.fleets)}"
    fleet = Fleet(id=new_id, owner=owner, ships=ships, position=planet_id)
    game_state.fleets[new_id] = fleet
    faction.fleets.append(new_id)

    game_state.add_event("fleet_created", owner, f"{game_state.factions[owner].name} 在 {planet.name} 组建了舰队", {"fleet": new_id})
    return jsonify({"success": True, "fleet": fleet.to_dict()})


@app.route('/api/fleet/drag', methods=['POST'])
def drag_fleet():
    """通过前端拖拽下达移动或巡逻命令。
    body: { owner, fleet_id, target: { type: 'planet'|'edge', planet_id?:str, a?:str, b?:str } }
    - type=planet: 移动到相邻星球 planet_id
    - type=edge: 在连线(a,b)上巡逻
    """
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    owner = data.get('owner', 'player')
    fid = data.get('fleet_id')
    target = data.get('target') or {}
    if not fid or fid not in game_state.fleets:
        return jsonify({"success": False, "message": "舰队不存在"}), 404
    fleet = game_state.fleets[fid]
    if fleet.owner != owner:
        return jsonify({"success": False, "message": "只能操作己方舰队"}), 403

    ttype = (target.get('type') or '').lower()
    if ttype == 'planet':
        dest = target.get('planet_id')
        if dest not in game_state.planets:
            return jsonify({"success": False, "message": "目标星球不存在"}), 400
        neighbors = galaxy_gen.get_connected_planets(game_state, fleet.position)
        if dest not in neighbors:
            return jsonify({"success": False, "message": "目的地必须与当前位置相邻"}), 400
        stationed = sum(1 for f in game_state.fleets.values() if f.position == dest and f.owner == owner)
        # 分派上限：优先用势力自定义上限，否则使用行星船坞上限（TurnEngine里二次检查）
        cap_custom = game_state.factions[owner].planet_alloc_caps.get(dest)
        if cap_custom is not None:
            if stationed >= cap_custom:
                return jsonify({"success": False, "message": f"目标星球己方驻扎上限已满({cap_custom})"}), 400
        else:
            if stationed >= 5:
                return jsonify({"success": False, "message": "目标星球驻扎舰队已满(5)"}), 400
        fleet.destination = dest
        fleet.travel_progress = 0.0
        game_state.add_event("fleet_movement", owner, f"{game_state.factions[owner].name} 的舰队向 {game_state.planets[dest].name} 移动", {"fleet": fid, "destination": dest})
        return jsonify({"success": True, "mode": "move", "fleet": fleet.to_dict()})
    elif ttype == 'edge':
        a = target.get('a')
        b = target.get('b')
        if not a or not b:
            return jsonify({"success": False, "message": "缺少连线端点"}), 400
        edge = (a, b)
        if edge not in game_state.connections and (b, a) not in game_state.connections:
            return jsonify({"success": False, "message": "该连线不存在"}), 400
        edge_key = "|".join(sorted([a, b]))
        cap = game_state.factions[owner].edge_alloc_caps.get(edge_key)
        if cap is not None:
            current = sum(1 for f in game_state.fleets.values() if f.patrol_edge == tuple(sorted([a, b])) and f.owner == owner)
            if current >= cap:
                return jsonify({"success": False, "message": f"该连线巡逻上限已满({cap})"}), 400
        fleet.patrol_edge = tuple(sorted([a, b]))
        game_state.add_event("fleet_patrol", owner, f"舰队 {fid} 正在巡逻 {a} - {b}", {"fleet": fid, "edge": [a, b]})
        return jsonify({"success": True, "mode": "patrol", "fleet": fleet.to_dict()})
    else:
        return jsonify({"success": False, "message": "未知目标类型"}), 400


@app.route('/api/fleet/reinforce', methods=['POST'])
def reinforce_fleet():
    """为己方舰队增补或回收舰船。body: { owner, fleet_id, delta: {type: +/-n} }
    正数表示添置（消耗资源），负数表示回收（返还50%资源）。
    """
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    owner = data.get('owner', 'player')
    fid = data.get('fleet_id')
    delta = data.get('delta') or {}
    if fid not in game_state.fleets:
        return jsonify({"success": False, "message": "舰队不存在"}), 404
    fleet = game_state.fleets[fid]
    if fleet.owner != owner:
        return jsonify({"success": False, "message": "只能操作己方舰队"}), 400
    faction = game_state.factions[owner]
    cost_table = {
        'scout': (1, 3), 'corvette': (3, 6), 'destroyer': (8, 12), 'cruiser': (20, 30), 'battleship': (50, 80)
    }
    map_type = {
        'scout': ShipType.SCOUT, 'corvette': ShipType.CORVETTE, 'destroyer': ShipType.DESTROYER,
        'cruiser': ShipType.CRUISER, 'battleship': ShipType.BATTLESHIP
    }
    # 计算资源变化
    need_min = need_en = 0.0
    refund_min = refund_en = 0.0
    for k, dv in delta.items():
        dv = int(dv or 0)
        if k not in cost_table or dv == 0:
            continue
        m, e = cost_table[k]
        if dv > 0:
            need_min += m * dv
            need_en += e * dv
        else:
            refund_min += m * (-dv) * 0.5
            refund_en += e * (-dv) * 0.5
    if need_min > 0 or need_en > 0:
        if faction.resources.minerals < need_min or faction.resources.energy < need_en:
            return jsonify({"success": False, "message": "资源不足"}), 400
        faction.resources.minerals -= need_min
        faction.resources.energy -= need_en
    # 返还
    faction.resources.minerals += refund_min
    faction.resources.energy += refund_en
    # 应用到舰队
    for k, dv in delta.items():
        dv = int(dv or 0)
        if k not in map_type or dv == 0:
            continue
        st = map_type[k]
        cur = fleet.ships.get(st, 0)
        cur += dv
        if cur < 0:
            cur = 0
        fleet.ships[st] = cur
    game_state.add_event("fleet_reinforced", owner, f"{faction.name} 调整了舰队编制", {"fleet": fid, "delta": delta})
    return jsonify({"success": True, "fleet": fleet.to_dict(), "refund": {"minerals": refund_min, "energy": refund_en}})


@app.route('/api/fleet/move', methods=['POST'])
def move_fleet():
    """下达舰队移动命令到相邻星球。body: { owner, fleet_id, destination }"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    owner = data.get('owner', 'player')
    fid = data.get('fleet_id')
    dest = data.get('destination')
    if fid not in game_state.fleets:
        return jsonify({"success": False, "message": "舰队不存在"}), 404
    fleet = game_state.fleets[fid]
    if fleet.owner != owner:
        return jsonify({"success": False, "message": "只能移动己方舰队"}), 400
    if dest not in game_state.planets:
        return jsonify({"success": False, "message": "目标星球不存在"}), 400
    # 只能移动到相邻
    neighbors = galaxy_gen.get_connected_planets(game_state, fleet.position)
    if dest not in neighbors:
        return jsonify({"success": False, "message": "目的地必须与当前位置相邻"}), 400
    # 设置目的地，真实移动由回合引擎处理；简单预检：目标星球驻扎上限（到达时仍会再次检查）
    stationed = sum(1 for f in game_state.fleets.values() if f.position == dest)
    if stationed >= 5:
        return jsonify({"success": False, "message": "目标星球驻扎舰队已满(5)"}), 400
    # 设置目的地
    fleet.destination = dest
    fleet.travel_progress = 0.0
    game_state.add_event("fleet_movement", owner, f"{game_state.factions[owner].name} 的舰队向 {game_state.planets[dest].name} 移动", {"fleet": fid, "destination": dest})
    return jsonify({"success": True, "fleet": fleet.to_dict()})


@app.route('/api/alloc/planet', methods=['POST'])
def set_planet_alloc_cap():
    """设置某己方星球的己方驻军上限。body: { owner, planet_id, cap } cap>=0 
    说明：仅限制该势力自己的舰队数量，不影响其他势力。"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    owner = data.get('owner', 'player')
    pid = data.get('planet_id')
    cap = data.get('cap')
    if owner not in game_state.factions:
        return jsonify({"success": False, "message": "势力不存在"}), 400
    if pid not in game_state.planets:
        return jsonify({"success": False, "message": "星球不存在"}), 400
    if game_state.planets[pid].owner != owner:
        return jsonify({"success": False, "message": "只能设置己方星球"}), 403
    try:
        cap = int(cap)
        if cap < 0:
            return jsonify({"success": False, "message": "上限必须是非负整数"}), 400
    except Exception:
        return jsonify({"success": False, "message": "cap 参数无效"}), 400
    game_state.factions[owner].planet_alloc_caps[pid] = cap
    game_state.add_event("alloc_set", owner, f"设置 {game_state.planets[pid].name} 驻军上限为 {cap}", {"planet": pid, "cap": cap})
    return jsonify({"success": True, "planet_alloc_caps": game_state.factions[owner].planet_alloc_caps})


@app.route('/api/alloc/edge', methods=['POST'])
def set_edge_alloc_cap():
    """设置某条连线的己方巡逻上限。body: { owner, a, b, cap }"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    owner = data.get('owner', 'player')
    a = data.get('a')
    b = data.get('b')
    cap = data.get('cap')
    if owner not in game_state.factions:
        return jsonify({"success": False, "message": "势力不存在"}), 400
    if not a or not b:
        return jsonify({"success": False, "message": "缺少连线端点"}), 400
    if (a, b) not in game_state.connections and (b, a) not in game_state.connections:
        return jsonify({"success": False, "message": "该连线不存在"}), 400
    try:
        cap = int(cap)
        if cap < 0:
            return jsonify({"success": False, "message": "上限必须是非负整数"}), 400
    except Exception:
        return jsonify({"success": False, "message": "cap 参数无效"}), 400
    key = "|".join(sorted([a, b]))
    game_state.factions[owner].edge_alloc_caps[key] = cap
    game_state.add_event("alloc_set", owner, f"设置连线 {a}-{b} 巡逻上限为 {cap}", {"edge": [a, b], "cap": cap})
    return jsonify({"success": True, "edge_alloc_caps": game_state.factions[owner].edge_alloc_caps})


@app.route('/api/game/power_stats', methods=['GET'])
def power_stats():
    """返回各势力综合实力分解与总分，用于前端展示条形图或列表。
    形如 { success, stats: [{ id, name, breakdown:{resources, planets, population, defense, fleets, tech, reputation_mod}, total }] }
    """
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    # 复用 calculate_faction_power 的口径，给出构成分解
    from game_engine import BuildingType
    stats = []
    leaders = _get_assault_always_factions()
    for fid, f in game_state.factions.items():
        resource_score = (
            f.resources.energy * 0.6 +
            f.resources.minerals * 0.8 +
            f.resources.research * 1.0
        )
        planet_score = len(f.planets) * 120.0
        population_score = 0.0
        defense_score = 0.0
        for pid in f.planets:
            p = game_state.planets.get(pid)
            if not p:
                continue
            population_score += p.population * 1.5
            defense_score += sum(1 for b in p.buildings if b == BuildingType.DEFENSE_STATION) * 50.0
        fleet_power = 0.0
        fleet_count = len(f.fleets or [])
        ship_count_total = 0
        for fleet_id in f.fleets:
            fl = game_state.fleets.get(fleet_id)
            if fl:
                fleet_power += fl.get_strength() * 2.0
                # 统计舰船总艘数
                try:
                    ship_count_total += sum(int(v) for v in (fl.ships or {}).values())
                except Exception:
                    for v in (fl.ships or {}).values():
                        try:
                            ship_count_total += int(v)
                        except Exception:
                            pass
        tech_count = len(f.technologies or [])
        tech_score = tech_count * 90.0
        reputation_mod = 1.0 + max(-0.3, min(0.3, (f.reputation - 50) / 200))
        subtotal = resource_score + planet_score + population_score + defense_score + fleet_power + tech_score
        total = subtotal * reputation_mod
        stats.append({
            "id": fid,
            "name": f.name,
            "breakdown": {
                "resources": resource_score,
                "planets": planet_score,
                "population": population_score,
                "defense": defense_score,
                "fleets": fleet_power,
                "tech": tech_score,
                "reputation_mod": reputation_mod
            },
            "total": total,
            # 额外补充指标：便于前端更细颗粒展示
            "extras": {
                "fleet_count": fleet_count,
                "ship_count_total": ship_count_total,
                "tech_count": tech_count,
                "assault_always": (fid in leaders)
            }
        })
    # 围攻聚合：填充每势力在 extras 中的围攻统计
    try:
        siege = getattr(game_state, 'siege', {}) or {}
        # 预计算每势力作为进攻方的 (星球数, 点数总和)
        atk_planet_cnt = {fid: 0 for fid in game_state.factions.keys()}
        atk_points_sum = {fid: 0 for fid in game_state.factions.keys()}
        def_planet_cnt = {fid: 0 for fid in game_state.factions.keys()}
        def_points_sum = {fid: 0 for fid in game_state.factions.keys()}
        for pid, mp in siege.items():
            # 攻方统计
            for aid, pts in mp.items():
                if pts > 0 and aid in atk_planet_cnt:
                    atk_planet_cnt[aid] += 1
                    atk_points_sum[aid] += int(pts)
            # 守方统计：该星球当前主人（若有）累计被围攻点数
            planet = game_state.planets.get(pid)
            owner = getattr(planet, 'owner', None)
            if owner and owner in def_planet_cnt:
                # 该星球受到的总点数
                total_pts = sum(int(v) for v in mp.values() if int(v) > 0)
                if total_pts > 0:
                    def_planet_cnt[owner] += 1
                    def_points_sum[owner] += total_pts
        # 写回到 stats.extras
        for s in stats:
            fid = s.get("id")
            ex = s.setdefault("extras", {})
            ex["siege_attacking_planets"] = atk_planet_cnt.get(fid, 0)
            ex["siege_attacking_points"] = atk_points_sum.get(fid, 0)
            ex["siege_defending_planets"] = def_planet_cnt.get(fid, 0)
            ex["siege_defending_points"] = def_points_sum.get(fid, 0)
    except Exception:
        pass
    # 按总分降序
    stats.sort(key=lambda s: s["total"], reverse=True)
    return jsonify({"success": True, "stats": stats})


@app.route('/api/fleet/patrol', methods=['POST'])
def patrol_fleet():
    """设置或取消舰队在一条连线上的巡逻。
    body: { owner, fleet_id, a, b } 若 a/b 缺失则为取消巡逻。
    """
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    owner = data.get('owner', 'player')
    fid = data.get('fleet_id')
    a = data.get('a')
    b = data.get('b')
    if not fid or fid not in game_state.fleets:
        return jsonify({"success": False, "message": "舰队不存在"}), 404
    fleet = game_state.fleets[fid]
    if fleet.owner != owner:
        return jsonify({"success": False, "message": "只能操作己方舰队"}), 403

    # 取消巡逻
    if not a or not b:
        fleet.patrol_edge = None
        game_state.add_event("fleet_patrol", owner, f"舰队 {fid} 结束巡逻", {"fleet": fid})
        return jsonify({"success": True, "fleet": fleet.to_dict()})

    # 校验边存在（无向）
    edge = (a, b)
    rev = (b, a)
    if edge not in game_state.connections and rev not in game_state.connections:
        return jsonify({"success": False, "message": "该连线不存在"}), 400

    fleet.patrol_edge = tuple(sorted([a, b]))
    game_state.add_event("fleet_patrol", owner, f"舰队 {fid} 正在巡逻 {a} - {b}", {"fleet": fid, "edge": [a, b]})
    return jsonify({"success": True, "fleet": fleet.to_dict()})


@app.route('/api/game/victory_progress', methods=['GET'])
def get_victory_progress():
    """胜利条件进度（默认返回玩家 player 的视角）"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400

    fid = request.args.get('faction_id', 'player')
    faction = game_state.factions.get(fid)
    if not faction:
        return jsonify({"success": False, "message": "势力不存在"}), 404

    cfg = getattr(game_state, 'victory_config', {}) or {}

    # 科技胜进度
    tech_required = cfg.get('tech_required_ids', [])
    tech_threshold = float(cfg.get('tech_score_threshold', 0.0) or 0.0)
    owned_set = set(faction.technologies)
    required_progress = [
        {"id": tid, "done": tid in owned_set, "name": (game_state.technologies.get(tid).name if game_state.technologies.get(tid) else tid)}
        for tid in tech_required
    ]
    total_cost = 0.0
    for tid in faction.technologies:
        t = game_state.technologies.get(tid)
        if t:
            total_cost += t.cost

    # 经济胜进度
    window = int(cfg.get('econ_window', 3) or 3)
    threshold = float(cfg.get('econ_threshold', 0.0) or 0.0)
    # my 最近 window 分数
    # hist = (game_state.econ_history.get(fid) or [])[-window:]
    # 计算最近 window 回合每个回合是否领先且达标
    recent_scores = {}
    for ofid, ohist in game_state.econ_history.items():
        recent_scores[ofid] = ohist[-window:] if len(ohist) >= window else []
    econ_per_turn = []
    # 计算可比较的回合数：取 window 与所有势力可用历史长度的最小值；若没有可用历史则为 0
    lengths = [len(v) for v in recent_scores.values() if v]
    limit = min(window, min(lengths)) if lengths else 0
    for i in range(limit):
        turn_scores = [recent_scores[ofid][i] for ofid in recent_scores.keys() if len(recent_scores[ofid]) > i]
        if not turn_scores:
            continue
        max_i = max(turn_scores)
        my_i = recent_scores.get(fid, [])
        my_val = my_i[i] if len(my_i) > i else 0.0
        econ_per_turn.append({
            "score": my_val,
            "threshold_ok": my_val >= threshold,
            "is_leading": abs(my_val - max_i) < 1e-6
        })

    return jsonify({
        "success": True,
        "victory_config": cfg,
        "game_over": game_state.game_over,
        "winner": game_state.winner,
        "end_reason": game_state.end_reason,
        "tech_progress": {
            "required": required_progress,
            "threshold": tech_threshold,
            "completed_cost": total_cost
        },
        "economic_progress": {
            "window": window,
            "threshold": threshold,
            "recent": econ_per_turn
        }
    })


@app.route('/api/game/continue', methods=['POST'])
def enable_postgame():
    """允许战后继续推进回合（沙盒/观战）。body: { enable: bool }"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    enable = bool(data.get('enable', True))
    game_state.allow_postgame = enable
    msg = "已开启战后继续" if enable else "已关闭战后继续"
    game_state.add_event("postgame_toggle", None, msg, {"enable": enable})
    return jsonify({"success": True, "allow_postgame": game_state.allow_postgame, "game_state": game_state.to_dict()})


@app.route('/api/game/ai_takeover', methods=['POST'])
def toggle_ai_takeover():
    """切换AI接管玩家势力。body: { enable: bool }"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    enable = bool(data.get('enable', True))
    game_state.ai_takeover_player = enable
    # 将玩家标记为AI
    if 'player' in game_state.factions:
        game_state.factions['player'].is_ai = enable
    msg = "AI 已接管玩家" if enable else "AI 接管已关闭"
    game_state.add_event("ai_takeover_toggle", 'player', msg, {"enable": enable})
    return jsonify({"success": True, "ai_takeover_player": game_state.ai_takeover_player, "game_state": game_state.to_dict()})


@app.route('/api/game/planet_rename', methods=['POST'])
def rename_planet():
    """重命名星球：仅允许拥有者。body: { planet_id, new_name }"""
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    pid = data.get('planet_id')
    new_name = (data.get('new_name') or '').strip()
    if not pid or pid not in game_state.planets:
        return jsonify({"success": False, "message": "星球不存在"}), 404
    planet = game_state.planets[pid]
    if planet.owner != 'player':
        return jsonify({"success": False, "message": "只能重命名己方星球"}), 403
    if not new_name or len(new_name) > 24:
        return jsonify({"success": False, "message": "名称为空或过长(<=24)"}), 400
    # 基本字符过滤（只允许中英文、数字、空格、下划线、连字符）
    import re
    if not re.match(r'^[\w\-\u4e00-\u9fa5 ]+$', new_name):
        return jsonify({"success": False, "message": "名称包含非法字符"}), 400
    old = planet.name
    planet.name = new_name
    game_state.add_event("planet_renamed", planet.owner, f"{old} 重命名为 {new_name}", {"planet": pid})
    return jsonify({"success": True, "planet": planet.to_dict()})


@app.route('/api/game/planet_position', methods=['POST'])
def set_planet_position():
    """保存前端拖拽的星球坐标。
    接受 { positions: [{id, x, y}, ...] } 或单个 {id, x, y}
    """
    if game_state is None:
        return jsonify({"success": False, "message": "游戏未初始化"}), 400
    data = request.get_json(silent=True) or {}
    updates = []
    if 'positions' in data and isinstance(data['positions'], list):
        updates = data['positions']
    elif all(k in data for k in ('id', 'x', 'y')):
        updates = [data]
    count = 0
    for item in updates:
        pid = item.get('id')
        x = item.get('x')
        y = item.get('y')
        if pid in game_state.planets and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            p = game_state.planets[pid]
            p.position = (int(x), int(y))
            count += 1
    return jsonify({"success": True, "updated": count})


if __name__ == '__main__':
    # 自动创建static目录
    os.makedirs('static', exist_ok=True)
    # 尝试加载本地 .env（如果存在），方便本地开发使用环境变量
    load_dotenv()

    deepseek_configured = bool(os.getenv('DEEPSEEK_API_KEY'))

    print("=" * 60)
    print("Glax War - 4X Strategy Game Server")
    print("=" * 60)
    print("服务器启动在 http://localhost:5000")
    print("使用 GET /api/game/new 创建新游戏")
    print(f"Deepseek 已配置: {'是' if deepseek_configured else '否'}")
    print("注意：服务器不会在日志中打印 API Key。")
    print("=" * 60)

    app.run(debug=True, host='0.0.0.0', port=5000)
