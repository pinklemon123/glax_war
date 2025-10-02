"""
Flask服务器
提供REST API接口
"""
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import os
import random

from game_engine import (
    GameState, Faction, Resources, Command, CommandType,
    Technology, Fleet, ShipType, DiplomacyStatus
)
from galaxy_generator import GalaxyGenerator
from ai_system import AISystem
from turn_engine import TurnEngine


app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# 全局游戏状态
game_state = None
galaxy_gen = None
ai_system = None
turn_engine = None


def initialize_game(num_planets=30, num_ai=3):
    """初始化游戏"""
    global game_state, galaxy_gen, ai_system, turn_engine
    
    # 生成星系
    galaxy_gen = GalaxyGenerator(num_planets=num_planets, seed=random.randint(1, 10000))
    game_state = galaxy_gen.generate()
    
    # 创建科技树
    _initialize_technologies()
    
    # 创建势力
    _initialize_factions(num_ai)
    
    # 初始化AI和回合引擎
    ai_system = AISystem(game_state, galaxy_gen)
    turn_engine = TurnEngine(game_state, galaxy_gen)
    
    game_state.add_event("game_start", None, "游戏开始！")
    
    return game_state


def _initialize_technologies():
    """初始化科技树"""
    technologies = [
        Technology("tech_laser", "激光武器", 100.0),
        Technology("tech_shields", "能量护盾", 150.0),
        Technology("tech_ftl", "超光速引擎", 200.0),
        Technology("tech_colonization", "殖民技术", 120.0),
        Technology("tech_mining", "高级采矿", 130.0),
        Technology("tech_power", "聚变能源", 140.0),
    ]
    
    for tech in technologies:
        game_state.technologies[tech.id] = tech


def _initialize_factions(num_ai):
    """初始化势力"""
    # 创建玩家势力
    player = Faction(
        id="player",
        name="人类联邦",
        is_ai=False,
        resources=Resources(energy=500, minerals=500, research=100)
    )
    game_state.factions[player.id] = player
    
    # 创建AI势力
    ai_names = ["克林贡帝国", "罗慕伦星际帝国", "瓦肯共和国", "卡达西联盟", "费伦吉同盟"]
    for i in range(num_ai):
        ai_faction = Faction(
            id=f"ai_{i}",
            name=ai_names[i] if i < len(ai_names) else f"AI势力{i}",
            is_ai=True,
            resources=Resources(energy=500, minerals=500, research=100)
        )
        game_state.factions[ai_faction.id] = ai_faction
    
    # 为每个势力分配起始星球
    available_planets = list(game_state.planets.keys())
    random.shuffle(available_planets)
    
    for i, faction in enumerate(game_state.factions.values()):
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
    
    state = initialize_game(num_planets, num_ai)
    
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
    
    return jsonify({
        "success": True,
        "planet": planet.to_dict(),
        "connected_planets": connected
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


if __name__ == '__main__':
    # 自动创建static目录
    os.makedirs('static', exist_ok=True)
    
    print("=" * 60)
    print("Glax War - 4X Strategy Game Server")
    print("=" * 60)
    print("服务器启动在 http://localhost:5000")
    print("使用 GET /api/game/new 创建新游戏")
    print("=" * 60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)
