"""
核心游戏引擎
实现4X策略游戏的核心逻辑
"""
import random
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
import json


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
            "resource_production": self.resource_production.to_dict()
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
            "travel_progress": self.travel_progress
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
            "reputation": self.reputation
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
    
    def to_dict(self):
        return {
            "turn": self.turn,
            "planets": {k: v.to_dict() for k, v in self.planets.items()},
            "factions": {k: v.to_dict() for k, v in self.factions.items()},
            "fleets": {k: v.to_dict() for k, v in self.fleets.items()},
            "technologies": {k: v.to_dict() for k, v in self.technologies.items()},
            "connections": self.connections,
            "events": [e.to_dict() for e in self.events[-20:]]  # 只返回最近20个事件
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
