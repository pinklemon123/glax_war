"""
LLM 驱动的 AI 决策模块（可选）

通过环境变量启用：
- LLM_AI_ENABLED=1            开启 LLM 决策（默认关闭）
- LLM_PROVIDER=deepseek|openai  指定提供商

Deepseek：
- DEEPSEEK_API_KEY=...       必填
- 可选 DEEPSEEK_API_BASE=https://api.deepseek.com/v1
- 可选 LLM_MODEL=deepseek-chat

OpenAI：
- OPENAI_API_KEY=...         必填
- 可选 OPENAI_API_BASE=https://api.openai.com/v1
- 可选 LLM_MODEL=gpt-4o-mini

注意：本模块在容器内运行，网络/API 可用性以用户环境为准；失败将回退到规则式AI。
"""
from __future__ import annotations
import os
import json
import requests
from typing import List, Dict, Any, Optional
from game_engine import Command, CommandType, GameState


def _is_enabled() -> bool:
    v = os.getenv('LLM_AI_ENABLED', '0').strip().lower()
    return v in ('1', 'true', 'yes', 'on')


def _provider(override: str | None = None) -> str:
    if override:
        return override.strip().lower()
    return (os.getenv('LLM_PROVIDER') or 'deepseek').strip().lower()


def _api_config(provider_override: str | None = None) -> Dict[str, str]:
    prov = _provider(provider_override)
    if prov == 'openai':
        return {
            'base': os.getenv('OPENAI_API_BASE', 'https://api.openai.com/v1'),
            'key': os.getenv('OPENAI_API_KEY', ''),
            'model': (
                os.getenv('OPENAI_MODEL')
                or os.getenv('LLM_MODEL')
                or 'gpt-4o-mini'
            )
        }
    # default deepseek
    return {
        'base': os.getenv('DEEPSEEK_API_BASE', 'https://api.deepseek.com/v1'),
        'key': os.getenv('DEEPSEEK_API_KEY', ''),
        'model': (
            os.getenv('DEEPSEEK_MODEL')
            or os.getenv('LLM_MODEL')
            or 'deepseek-chat'
        )
    }


def _summarize_state_for_llm(gs: GameState, faction_id: str) -> Dict[str, Any]:
    f = gs.factions.get(faction_id)
    if not f:
        return {}
    # 精简摘要，控制 token：
    planets = []
    for pid in f.planets[:8]:
        p = gs.planets.get(pid)
        if not p:
            continue
        planets.append({
            'id': p.id,
            'name': p.name,
            'pop': p.population,
            'buildings': [b.value for b in p.buildings]
        })
    fleets = []
    for fid in f.fleets[:8]:
        fl = gs.fleets.get(fid)
        if not fl:
            continue
        fleets.append({
            'id': fl.id,
            'pos': fl.position,
            'ships': {k.value: v for k, v in (fl.ships or {}).items()}
        })
    # 列出邻接空白星球候选（最多8个）
    empty_neighbors = []
    seen = set()
    for pid in f.planets:
        for nid in _get_neighbors(gs, pid):
            if gs.planets.get(nid) and not gs.planets[nid].owner and nid not in seen:
                empty_neighbors.append({'from': pid, 'to': nid, 'name': gs.planets[nid].name})
                seen.add(nid)
            if len(empty_neighbors) >= 8:
                break
        if len(empty_neighbors) >= 8:
            break
    return {
        'turn': gs.turn,
        'resources': f.resources.to_dict(),
        'planets': planets,
        'fleets': fleets,
        'techs': list(f.technologies)[:12],
        'empty_neighbors': empty_neighbors
    }


def _get_neighbors(gs: GameState, pid: str) -> List[str]:
    res = []
    for a, b in gs.connections:
        if a == pid:
            res.append(b)
        elif b == pid:
            res.append(a)
    return res


def suggest_commands(gs: GameState, faction_id: str, provider: str | None = None) -> List[Command]:
    """若启用LLM，向提供商请求一次 JSON 决策；失败或关闭则返回空列表。"""
    if not _is_enabled():
        return []
    cfg = _api_config(provider)
    if not cfg.get('key'):
        return []

    prompt = {
        'role': 'system',
        'content': (
            '你是4X策略游戏的AI参谋，请基于给定的势力快照，返回当回合的少量指令（不超过4条）。\n'
            '可用指令（以 JSON 返回）：\n'
            '- build: { planet, building } building ∈ [energy_plant, mining_station, research_lab, shipyard, defense_station]\n'
            '- research: { technology } technology 来自可研究科技，否则忽略\n'
            '- colonize: { from_planet, to_planet } 必须相邻且目标无主\n'
            '- move: { fleet, destination } destination 必须与 fleet 当前位置相邻\n'
            '- strategy: { mode } mode ∈ [peace, defend, attack] ; attack 时可加 { target }\n'
            '请仅返回 JSON：{"actions": [...]}，不要夹杂解释文字。'
        )
    }
    user = {
        'role': 'user',
        'content': json.dumps(_summarize_state_for_llm(gs, faction_id), ensure_ascii=False)
    }
    try:
        data = _chat_completion(cfg, [prompt, user])
        text = _extract_text(data)
        obj = json.loads(text)
        actions = obj.get('actions') or []
        return _convert_actions_to_commands(gs, faction_id, actions)
    except Exception:
        return []


def _chat_completion(cfg: Dict[str, str], messages: List[Dict[str, str]]) -> Dict[str, Any]:
    base = cfg['base'].rstrip('/')
    url = f"{base}/chat/completions"
    headers = {
        'Authorization': f"Bearer {cfg['key']}",
        'Content-Type': 'application/json'
    }
    payload = {
        'model': cfg['model'],
        'messages': messages,
        'temperature': 0.2
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=12)
    resp.raise_for_status()
    return resp.json()


def _extract_text(resp: Dict[str, Any]) -> str:
    try:
        return resp['choices'][0]['message']['content']
    except Exception:
        return ''


def _convert_actions_to_commands(gs: GameState, faction_id: str, actions: List[Dict[str, Any]]) -> List[Command]:
    cmds: List[Command] = []
    f = gs.factions.get(faction_id)
    if not f:
        return cmds
    # 简单校验并最多接受4条
    for act in actions[:4]:
        if not isinstance(act, dict):
            continue
        t = (act.get('type') or act.get('command') or '').lower()
        if t == 'build':
            pid = act.get('planet')
            b = act.get('building')
            if pid in f.planets and gs.planets.get(pid) and b in {'energy_plant','mining_station','research_lab','shipyard','defense_station'}:
                cmds.append(Command(faction_id=faction_id, command_type=CommandType.BUILD, parameters={'planet': pid, 'building': b}))
        elif t == 'research':
            tech = act.get('technology')
            if tech and tech in gs.technologies and tech not in f.technologies and tech not in f.research_progress:
                cmds.append(Command(faction_id=faction_id, command_type=CommandType.RESEARCH, parameters={'technology': tech}))
        elif t == 'colonize':
            a = act.get('from_planet')
            b = act.get('to_planet')
            if a in f.planets and gs.planets.get(b) and not gs.planets[b].owner and (a,b) in gs.connections or (b,a) in gs.connections:
                cmds.append(Command(faction_id=faction_id, command_type=CommandType.COLONIZE, parameters={'from_planet': a, 'to_planet': b}))
        elif t == 'move':
            fid = act.get('fleet')
            dest = act.get('destination')
            if fid in f.fleets and gs.fleets.get(fid) and dest in gs.planets and ((gs.fleets[fid].position, dest) in gs.connections or (dest, gs.fleets[fid].position) in gs.connections):
                cmds.append(Command(faction_id=faction_id, command_type=CommandType.MOVE, parameters={'fleet': fid, 'destination': dest}))
        elif t == 'strategy':
            mode = act.get('mode')
            params = {'mode': mode}
            if mode == 'attack' and act.get('target'):
                params['target'] = act['target']
            if mode in {'peace','defend','attack'}:
                cmds.append(Command(faction_id=faction_id, command_type=CommandType.STRATEGY, parameters=params))
    return cmds


# ---------- Postgame Narrative ----------
def _build_markdown_chronicle(gs: GameState) -> str:
    """构造一份简洁的 Markdown 编年史，供 LLM 叙事作为素材。"""
    import time as _t
    lines: List[str] = []
    lines.append(f"# 星际编年史：第 {gs.turn} 回合")
    lines.append("")
    lines.append("## 势力名录")
    for f in gs.factions.values():
        lines.append(f"- {f.name}（ID: {f.id}） 行星 {len(f.planets)}，舰队 {len(f.fleets)}，声誉 {int(f.reputation)}")
    lines.append("")
    lines.append("## 大事记（时间序）")
    sorted_events = sorted(gs.events, key=lambda e: (e.turn, e.timestamp))
    for ev in sorted_events[-300:]:  # 控制长度
        ts = _t.strftime('%Y-%m-%d %H:%M:%S', _t.localtime(ev.timestamp))
        who = gs.factions.get(ev.faction).name if ev.faction in (gs.factions or {}) else (ev.faction or "-")
        lines.append(f"- 回合 {ev.turn}（{ts}）[{ev.event_type}] {who}: {ev.description}")
    lines.append("")
    # 实力排行
    if getattr(gs, 'power_history', None):
        try:
            last = gs.power_history[-1] if gs.power_history else {}
            if last:
                lines.append("## 终局实力排行（最近一回合）")
                for fid, sc in sorted(last.items(), key=lambda kv: kv[1], reverse=True):
                    nm = gs.factions.get(fid).name if fid in gs.factions else fid
                    lines.append(f"- {nm}: {sc:.1f}")
                lines.append("")
        except Exception:
            pass
    # 结算
    if gs.game_over:
        wname = gs.factions.get(gs.winner).name if gs.winner in gs.factions else (gs.winner or '-')
        lines.append("## 最终结算")
        lines.append(f"- 胜者：{wname}")
        lines.append(f"- 原因：{gs.end_reason}")
    return "\n".join(lines)


def generate_story_from_chronicle(gs: GameState, style: str | None = None, provider_override: str | None = None) -> str:
    """使用 LLM 阅读编年史，生成战后叙事。若未启用/无密钥，则返回空串。
    回退策略：若未显式指定 provider，当首选提供商失败或返回空时，且备选提供商存在密钥，则自动再尝试一次。
    """
    if not _is_enabled():
        return ''

    def _compose_and_call(cfg_local: Dict[str, str]) -> str:
        if not cfg_local.get('key'):
            return ''
        chronicle_md = _build_markdown_chronicle(gs)
        tone = (style or 'epic').strip().lower()
        tone_label = {
            'epic': '史诗叙事',
            'documentary': '纪实口吻',
            'news': '新闻播报'
        }.get(tone, '史诗叙事')
        sys = {
            'role': 'system',
            'content': (
                '你是科幻作家与历史学家，擅长用中文撰写战后编年史。'
                '请根据提供的“游戏编年史”材料，生成一篇可读性极强的宇宙历史叙事。\n'
                f'写作风格：{tone_label}；要求：分章节，点出主要势力、关键转折、战争走向、科技突破、人物群像（可合理想象），'
                '避免流水账，结构清晰，适度抒情与细节描绘。结尾给出对宇宙格局的评述。'
            )
        }
        user = {
            'role': 'user',
            'content': '以下是本局“游戏编年史（Markdown）”，请据此撰写完整叙事：\n\n' + chronicle_md
        }
        try:
            data = _chat_completion(cfg_local, [sys, user])
            text = _extract_text(data)
            return (text or '').strip()
        except Exception:
            return ''

    # 首次尝试：指定或默认提供商
    cfg = _api_config(provider_override)
    result = _compose_and_call(cfg)
    if result:
        return result

    # 若显式指定了提供商，则不进行回退
    if provider_override:
        return ''

    # 自动回退：尝试另一个提供商（仅在其密钥存在时）
    prim = _provider(None)
    alt = 'openai' if prim != 'openai' else 'deepseek'
    alt_cfg = _api_config(alt)
    if alt_cfg.get('key'):
        return _compose_and_call(alt_cfg)
    return ''


def generate_rule_based_story(gs: GameState, style: str | None = None) -> str:
    """不依赖外部 API 的规则式叙事生成，作为 LLM 失败或未启用时的兜底。
    会基于势力名录、事件日志与实力快照拼装一篇结构化长文。
    """
    import time as _t
    tone = (style or 'epic').strip().lower()
    def H(t: str) -> str:
        return f"## {t}"
    def P(txt: str) -> str:
        return txt
    # 势力与概览
    lines: List[str] = []
    title = {
        'epic': '群星之下：余烬与新生',
        'documentary': '战后报告：一场银河冲突的剖面',
        'news': '星际早报特别版：终局纪要'
    }.get(tone, '群星之下：余烬与新生')
    lines.append(f"# {title}")
    lines.append("")
    # 起篇
    if tone == 'news':
        lines.append(P(f"本刊讯：截至第 {gs.turn} 回合，本局冲突落下帷幕。以下为来自战地的综合纪要。"))
    elif tone == 'documentary':
        lines.append(P(f"在第 {gs.turn} 回合的帷幕落下之前，我们跟随数据与见闻，复盘这场银河尺度的对抗。"))
    else:
        lines.append(P(f"第 {gs.turn} 回合的终焉，像是群星呼出的最后一口叹息。边界在战火中重绘，旧旗帜的灰烬里，新的徽记升起。"))
    lines.append("")
    # 势力名录
    lines.append(H('势力与版图'))
    for f in gs.factions.values():
        lines.append(P(f"- {f.name}（ID: {f.id}）：行星 {len(f.planets)}，舰队 {len(f.fleets)}，声誉 {int(f.reputation)}"))
    lines.append("")
    # 关键事件摘录
    lines.append(H('关键战报回放'))
    important_types = {"planet_conquered","planet_captured","defense_success","combat","research_completed","colonization"}
    evs = [ev for ev in sorted(gs.events, key=lambda e: (e.turn, e.timestamp)) if ev.event_type in important_types]
    for ev in evs[-80:]:
        ts = _t.strftime('%Y-%m-%d %H:%M:%S', _t.localtime(ev.timestamp))
        who = gs.factions.get(ev.faction).name if ev.faction in (gs.factions or {}) else (ev.faction or "-")
        lines.append(P(f"- 回合 {ev.turn}（{ts}）[{ev.event_type}] {who}: {ev.description}"))
    if not evs:
        lines.append(P("- （暂无关键事件记录）"))
    lines.append("")
    # 终局实力
    lines.append(H('实力与格局'))
    if getattr(gs, 'power_history', None) and gs.power_history:
        last = gs.power_history[-1]
        ranking = sorted(last.items(), key=lambda kv: kv[1], reverse=True)
        for fid, sc in ranking:
            nm = gs.factions.get(fid).name if fid in gs.factions else fid
            lines.append(P(f"- {nm}: {sc:.1f}"))
        lines.append("")
        if gs.game_over:
            wname = gs.factions.get(gs.winner).name if gs.winner in gs.factions else (gs.winner or '-')
            reason = gs.end_reason or '综合实力领先'
            lines.append(P(f"胜者：{wname}（{reason}）。"))
    else:
        lines.append(P("- （未记录到实力快照）"))
    lines.append("")
    # 叙事段落（按不同语气渲染）
    lines.append(H('走向与转折'))
    if tone == 'news':
        lines.append(P("据统计，攻守转换集中在数个关键回合，局部战场的快速突破叠加了对整体格局的牵引效应。"))
    elif tone == 'documentary':
        lines.append(P("我们观察到围攻失败的叠加效应改变了防守端的风险曲线，而滩头保护为新近占领带来了短期的战略缓冲。"))
    else:
        lines.append(P("有人在铁与火中破门，也有人在护盾的阴影下坚守。命运像潮水那样涌来，又被一寸寸推回。"))
    lines.append("")
    lines.append(H('科技与后勤'))
    if any('tech_' in t for f in gs.factions.values() for t in f.technologies):
        lines.append(P("科技扩张贯穿全局：能量护盾、推进引擎与武器火控的迭代，直接重塑了战斗的边际收益。"))
    else:
        lines.append(P("本局科技推进有限，更多的胜负来自资源调度与兵力投送效率。"))
    lines.append("")
    lines.append(H('尾声'))
    if tone == 'news':
        lines.append(P("本期纪要到此结束，更多细节以附录形式存档于编年史。"))
    elif tone == 'documentary':
        lines.append(P("战争并不终结历史，它只是迫使历史给出下一个答案。"))
    else:
        lines.append(P("群星仍在呼吸。边界之外，总有人在绘制下一幅星图。"))
    return "\n".join(lines)


def chat_reply(gs: GameState,
               user_text: str,
               history: Optional[List[Dict[str, str]]] = None,
               style: Optional[str] = None,
               provider_override: Optional[str] = None) -> str:
    """基于当前游戏的编年史上下文，生成一次对话回复。
    - 优先使用已配置的 LLM；
    - 失败时回退到规则式摘要/叙事。
    history 形如：[{role:'user'|'assistant', content:''}, ...]
    """
    # 若未启用 LLM：直接规则式回退
    if not _is_enabled():
        # 若用户显式要求写史，则给长文；否则给简短摘要
        text = (user_text or '').strip().lower()
        if any(k in text for k in ['历史', '編年', '编年', 'war', 'history']):
            return generate_rule_based_story(gs, style)
        # 简短摘要
        base = generate_rule_based_story(gs, style)
        return base.split('\n\n')[0]

    # 构造消息
    chronicle_md = _build_markdown_chronicle(gs)
    tone = (style or 'epic').strip().lower()
    tone_label = {
        'epic': '史诗叙事',
        'documentary': '纪实口吻',
        'news': '新闻播报'
    }.get(tone, '史诗叙事')
    sys = {
        'role': 'system',
        'content': (
            '你是资深的银河史学家与作家，请使用中文回答。' \
            f'当前写作偏好：{tone_label}。' \
            '遵循用户指示，可引用“编年史”中的事实，并在合适处进行合理想象补叙。'
        )
    }
    ctx = {
        'role': 'system',
        'content': '编年史（Markdown，供参考）：\n\n' + chronicle_md
    }
    msgs: List[Dict[str, str]] = [sys, ctx]
    # 附上简短历史记录，避免超长
    if history:
        for m in history[-10:]:
            r = (m.get('role') or '').strip()
            c = (m.get('content') or '').strip()
            if r in ('user', 'assistant') and c:
                msgs.append({'role': r, 'content': c})
    msgs.append({'role': 'user', 'content': user_text})

    # 调用首选提供商
    cfg = _api_config(provider_override)
    try:
        data = _chat_completion(cfg, msgs)
        text = _extract_text(data).strip()
        if text:
            return text
    except Exception:
        pass

    # 自动回退到另一家
    if not provider_override:
        prim = _provider(None)
        alt = 'openai' if prim != 'openai' else 'deepseek'
        alt_cfg = _api_config(alt)
        try:
            if alt_cfg.get('key'):
                data = _chat_completion(alt_cfg, msgs)
                text = _extract_text(data).strip()
                if text:
                    return text
        except Exception:
            pass

    # 最后回退到规则式
    text = (user_text or '').strip().lower()
    if any(k in text for k in ['历史', '編年', '编年', 'war', 'history']):
        return generate_rule_based_story(gs, style)
    base = generate_rule_based_story(gs, style)
    return base.split('\n\n')[0]
