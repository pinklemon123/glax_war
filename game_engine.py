"""
核心游戏引擎
实现4X策略游戏的核心逻辑
"""
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class ResourceType(Enum):
    """资源类型"""
    ENERGY = "energy"
    MINERALS = "minerals"
    RESEARCH = "research"


class PlanetType(Enum):
    """星球类型"""
    DESERT = "desert"
    OCEANIC = "oceanic"
    TROPICAL = "tropical"
    ARCTIC = "arctic"
    BARREN = "barren"
    GAS_GIANT = "gas_giant"


class BuildingType(Enum):
    """建筑类型"""
    ENERGY_PLANT = "energy_plant"
    MINING_STATION = "mining_station"
    RESEARCH_LAB = "research_lab"
    SHIPYARD = "shipyard"
    DEFENSE_STATION = "defense_station"


class ShipType(Enum):
    """舰船类型"""
    SCOUT = "scout"
    CORVETTE = "corvette"
    DESTROYER = "destroyer"
    CRUISER = "cruiser"
    BATTLESHIP = "battleship"


class DiplomacyStatus(Enum):
    """外交状态"""
    NEUTRAL = "neutral"
    FRIENDLY = "friendly"
    ALLIED = "allied"
    HOSTILE = "hostile"
    WAR = "war"


class CommandType(Enum):
    """指令类型"""
    COLONIZE = "colonize"
    BUILD = "build"
    MOVE = "move"
    RESEARCH = "research"
    DIPLOMACY = "diplomacy"
    TRADE = "trade"
    STRATEGY = "strategy"


@dataclass
class Resources:
    """资源数据结构"""
    energy: float = 0.0
    minerals: float = 0.0
    research: float = 0.0

    def add(self, other: 'Resources'):
        """添加资源"""
        self.energy += other.energy
        self.minerals += other.minerals
        self.research += other.research

    def subtract(self, other: 'Resources') -> bool:
        """减少资源，如果资源不足返回False"""
        if self.energy < other.energy or self.minerals < other.minerals or self.research < other.research:
            return False
        self.energy -= other.energy
        self.minerals -= other.minerals
        self.research -= other.research
        return True

    def to_dict(self):
        return {"energy": self.energy, "minerals": self.minerals, "research": self.research}


@dataclass
class Planet:
    """星球数据结构"""
    id: str
    name: str
    type: PlanetType
    position: tuple
    owner: Optional[str] = None
    population: int = 0
    buildings: List[BuildingType] = field(default_factory=list)
    resource_production: Resources = field(default_factory=Resources)
    # 强袭成功后的临时保护回合（滩头保护）：在该回合数之前，星球不可被再次夺取
    capture_protection_until_turn: int = 0
    
    def calculate_production(self) -> Resources:
        """计算星球资源产出"""
        production = Resources()
        # 基础产出
        production.energy = 5.0
        production.minerals = 3.0
        production.research = 1.0
        
        # 建筑加成
        for building in self.buildings:
            if building == BuildingType.ENERGY_PLANT:
                production.energy += 10.0
            elif building == BuildingType.MINING_STATION:
                production.minerals += 10.0
            elif building == BuildingType.RESEARCH_LAB:
                production.research += 10.0
        
        # 人口加成
        production.energy += self.population * 0.5
        production.minerals += self.population * 0.3
        production.research += self.population * 0.2
        
        return production

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "position": self.position,
            "owner": self.owner,
            "population": self.population,
            "buildings": [b.value for b in self.buildings],
            "resource_production": self.resource_production.to_dict(),
            "capture_protection_until_turn": self.capture_protection_until_turn
        }


@dataclass
class Fleet:
    """舰队数据结构"""
    id: str
    owner: str
    ships: Dict[ShipType, int]
    position: str  # 星球ID
    destination: Optional[str] = None
    travel_progress: float = 0.0
    patrol_edge: Optional[tuple] = None  # (planet_a, planet_b) 无向连线，规范化为(a<=b)
    # 熟练度：随作战/行动略微增长，可为后续战斗或事件提供修正
    proficiency: float = 0.0
    # 流亡来源：当势力失去全部星球时，原势力舰队将变为无主，并标记其来源势力
    exiled_from: Optional[str] = None
    
    def get_strength(self) -> int:
        """计算舰队战斗力"""
        strength = 0
        ship_power = {
            ShipType.SCOUT: 1,
            ShipType.CORVETTE: 3,
            ShipType.DESTROYER: 8,
            ShipType.CRUISER: 20,
            ShipType.BATTLESHIP: 50
        }
        for ship_type, count in self.ships.items():
            strength += ship_power[ship_type] * count
        return strength

    def to_dict(self):
        return {
            "id": self.id,
            "owner": self.owner,
            "ships": {k.value: v for k, v in self.ships.items()},
            "position": self.position,
            "destination": self.destination,
            "travel_progress": self.travel_progress,
            "patrol_edge": list(self.patrol_edge) if self.patrol_edge else None,
            "proficiency": self.proficiency,
            "exiled_from": self.exiled_from
        }


@dataclass
class Technology:
    """科技数据结构"""
    id: str
    name: str
    cost: float
    prerequisites: List[str] = field(default_factory=list)
    effects: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "cost": self.cost,
            "prerequisites": self.prerequisites,
            "effects": self.effects
        }


@dataclass
class Faction:
    """势力数据结构"""
    id: str
    name: str
    is_ai: bool
    resources: Resources = field(default_factory=Resources)
    planets: List[str] = field(default_factory=list)
    fleets: List[str] = field(default_factory=list)
    technologies: List[str] = field(default_factory=list)
    research_progress: Dict[str, float] = field(default_factory=dict)
    diplomacy: Dict[str, DiplomacyStatus] = field(default_factory=dict)
    reputation: float = 100.0  # 声誉值，0-100
    strategy_mode: str = "peace"  # peace/attack/defend
    war_target: Optional[str] = None
    defense_focus: List[str] = field(default_factory=list)
    attack_charges: int = 1
    defense_charges: int = 1
    # 分派限制：每个己方星球的驻军上限、每条边的巡逻上限（仅对该势力生效）
    planet_alloc_caps: Dict[str, int] = field(default_factory=dict)
    edge_alloc_caps: Dict[str, int] = field(default_factory=dict)  # key 采用 "a|b" 排序后拼接

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "is_ai": self.is_ai,
            "resources": self.resources.to_dict(),
            "planets": self.planets,
            "fleets": self.fleets,
            "technologies": self.technologies,
            "research_progress": self.research_progress,
            "diplomacy": {k: v.value for k, v in self.diplomacy.items()},
            "reputation": self.reputation,
            "strategy_mode": self.strategy_mode,
            "war_target": self.war_target,
            "defense_focus": self.defense_focus,
            "attack_charges": self.attack_charges,
            "defense_charges": self.defense_charges,
            "planet_alloc_caps": self.planet_alloc_caps,
            "edge_alloc_caps": self.edge_alloc_caps
        }


@dataclass
class GameEvent:
    """游戏事件"""
    turn: int
    timestamp: float
    event_type: str
    faction: Optional[str]
    description: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "turn": self.turn,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "faction": self.faction,
            "description": self.description,
            "data": self.data
        }


@dataclass
class Command:
    """玩家/AI指令"""
    faction_id: str
    command_type: CommandType
    parameters: Dict[str, Any]

    def to_dict(self):
        return {
            "faction_id": self.faction_id,
            "command_type": self.command_type.value,
            "parameters": self.parameters
        }


class GameState:
    """游戏状态"""
    def __init__(self):
        self.turn: int = 0
        self.planets: Dict[str, Planet] = {}
        self.factions: Dict[str, Faction] = {}
        self.fleets: Dict[str, Fleet] = {}
        self.technologies: Dict[str, Technology] = {}
        self.connections: List[tuple] = []  # 星球连接
        self.events: List[GameEvent] = []
        self.pending_commands: List[Command] = []
        # 规则配置
        self.rules: Dict[str, Any] = {
            # 无行星时的强袭占领阈值（> 阈值 才可强袭）
            "desperate_capture_threshold": 10
        }
        # 结束判定相关
        self.game_over: bool = False
        self.winner: Optional[str] = None
        self.end_reason: Optional[str] = None
        self.max_turns: int = 200
        self.final_scores: Dict[str, float] = {}
        # 战后继续/AI接管
        self.allow_postgame: bool = False           # 允许在游戏结束后继续推进回合（仅用于观战/沙盒）
        self.ai_takeover_player: bool = False       # 允许AI接管玩家势力
        # 停战相关
        self.game_start_time: float = 0.0
        self.truce_until: float = 0.0  # 时间戳，<=0 表示未启用
        # 胜利配置与经济历史
        self.victory_config: Dict[str, Any] = {
            "tech_victory_enabled": False,
            "tech_required_ids": [],            # 列表：完成这些科技即胜
            "tech_score_threshold": 0.0,        # 或：已完成科技成本总和达到阈值即胜
            "econ_victory_enabled": False,
            "econ_window": 3,                   # 连续 N 回合
            "econ_threshold": 200.0,            # 每回合最低产出分数
            "econ_weights": {                   # 折算权重
                "energy": 1.0,
                "minerals": 1.0,
                "research": 1.0
            }
        }
        self.econ_history: Dict[str, List[float]] = {}
        # 每回合综合评分快照
        self.power_history: List[Dict[str, float]] = []
        # 殖民计数（每势力每回合上限控制）
        self.colonize_counts: Dict[str, int] = {}
        # 围攻进度（planet_id -> {attacker_id: points}），用于降低该星球对特定进攻方的防御系数
        self.siege: Dict[str, Dict[str, int]] = {}
    
    def to_dict(self):
        return {
            "turn": self.turn,
            "planets": {k: v.to_dict() for k, v in self.planets.items()},
            "factions": {k: v.to_dict() for k, v in self.factions.items()},
            "fleets": {k: v.to_dict() for k, v in self.fleets.items()},
            "technologies": {k: v.to_dict() for k, v in self.technologies.items()},
            "connections": self.connections,
            "events": [e.to_dict() for e in self.events[-20:]],  # 只返回最近20个事件
            "game_over": self.game_over,
            "winner": self.winner,
            "end_reason": self.end_reason,
            "max_turns": self.max_turns,
            "final_scores": self.final_scores,
            "game_start_time": self.game_start_time,
            "truce_until": self.truce_until,
            "truce_active": (self.truce_until > 0 and time.time() < self.truce_until),
            "victory_config": self.victory_config,
            "allow_postgame": self.allow_postgame,
            "ai_takeover_player": self.ai_takeover_player,
            "econ_history": self.econ_history,
            "rules": self.rules,
            "power_history": self.power_history,
            "siege": self.siege
        }

    def add_event(self, event_type: str, faction: Optional[str], description: str, data: Dict[str, Any] = None):
        """添加游戏事件"""
        event = GameEvent(
            turn=self.turn,
            timestamp=time.time(),
            event_type=event_type,
            faction=faction,
            description=description,
            data=data or {}
        )
        self.events.append(event)
        return event


def calculate_faction_power(game_state: 'GameState', faction: Faction) -> float:
    """粗略评估一个势力的综合实力，用于殖民竞争和战略判定。"""
    resource_score = (
        faction.resources.energy * 0.6 +
        faction.resources.minerals * 0.8 +
        faction.resources.research * 1.0
    )

    planet_score = len(faction.planets) * 120.0
    population_score = 0.0
    defense_score = 0.0
    for planet_id in faction.planets:
        planet = game_state.planets.get(planet_id)
        if not planet:
            continue
        population_score += planet.population * 1.5
        defense_score += sum(1 for b in planet.buildings if b == BuildingType.DEFENSE_STATION) * 50.0

    fleet_power = 0.0
    for fleet_id in faction.fleets:
        fleet = game_state.fleets.get(fleet_id)
        if fleet:
            fleet_power += fleet.get_strength() * 2.0

    tech_score = len(faction.technologies) * 90.0

    reputation_mod = 1.0 + max(-0.3, min(0.3, (faction.reputation - 50) / 200))

    return (
        resource_score +
        planet_score +
        population_score +
        defense_score +
        fleet_power +
        tech_score
    ) * reputation_mod
