"""
AI决策系统
为AI势力生成行动决策
"""
import random
from typing import List
from game_engine import (
    GameState, Faction, Command, CommandType, 
    BuildingType, ShipType, DiplomacyStatus, Resources
)
from galaxy_generator import GalaxyGenerator


class AISystem:
    """AI决策系统"""
    
    def __init__(self, game_state: GameState, galaxy_gen: GalaxyGenerator):
        self.game_state = game_state
        self.galaxy_gen = galaxy_gen
    
    def generate_ai_commands(self, faction_id: str) -> List[Command]:
        """为AI势力生成指令"""
        faction = self.game_state.factions[faction_id]
        commands = []
        
        # 基于策略生成不同类型的指令
        commands.extend(self._decide_colonization(faction))
        commands.extend(self._decide_building(faction))
        commands.extend(self._decide_research(faction))
        commands.extend(self._decide_fleet_actions(faction))
        commands.extend(self._decide_diplomacy(faction))
        
        return commands
    
    def _decide_colonization(self, faction: Faction) -> List[Command]:
        """决定殖民行动"""
        commands = []
        
        # 查找未被占领的星球
        unoccupied = [p for p in self.game_state.planets.values() if p.owner is None]
        if not unoccupied or not faction.planets:
            return commands
        
        # 查找邻近的未占领星球
        for planet_id in faction.planets:
            connected = self.galaxy_gen.get_connected_planets(self.game_state, planet_id)
            for conn_id in connected:
                conn_planet = self.game_state.planets[conn_id]
                if conn_planet.owner is None:
                    # 检查是否有足够的资源
                    if faction.resources.minerals >= 100:
                        commands.append(Command(
                            faction_id=faction.id,
                            command_type=CommandType.COLONIZE,
                            parameters={"from_planet": planet_id, "to_planet": conn_id}
                        ))
                        break  # 每回合只殖民一个星球
            if commands:
                break
        
        return commands
    
    def _decide_building(self, faction: Faction) -> List[Command]:
        """决定建造行动"""
        commands = []
        
        # 为每个星球决定建造
        for planet_id in faction.planets:
            planet = self.game_state.planets[planet_id]
            
            # 限制每个星球的建筑数量
            if len(planet.buildings) >= 5:
                continue
            
            # 根据资源情况决定建造类型
            building_to_build = None
            cost = Resources(minerals=50, energy=50)
            
            if faction.resources.energy < 200:
                building_to_build = BuildingType.ENERGY_PLANT
            elif faction.resources.minerals < 200:
                building_to_build = BuildingType.MINING_STATION
            elif faction.resources.research < 100:
                building_to_build = BuildingType.RESEARCH_LAB
            elif random.random() > 0.7:
                building_to_build = BuildingType.SHIPYARD
            
            if building_to_build and faction.resources.subtract(cost):
                commands.append(Command(
                    faction_id=faction.id,
                    command_type=CommandType.BUILD,
                    parameters={"planet": planet_id, "building": building_to_build.value}
                ))
                # 恢复资源（因为这只是模拟）
                faction.resources.add(cost)
                break  # 每回合只建造一个建筑
        
        return commands
    
    def _decide_research(self, faction: Faction) -> List[Command]:
        """决定研究行动"""
        commands = []
        
        # 选择一个未研究的科技
        available_techs = [t for t in self.game_state.technologies.values() 
                          if t.id not in faction.technologies 
                          and t.id not in faction.research_progress]
        
        if available_techs and faction.resources.research >= 50:
            tech = random.choice(available_techs)
            commands.append(Command(
                faction_id=faction.id,
                command_type=CommandType.RESEARCH,
                parameters={"technology": tech.id}
            ))
        
        return commands
    
    def _decide_fleet_actions(self, faction: Faction) -> List[Command]:
        """决定舰队行动"""
        commands = []
        
        # 简单的舰队移动逻辑
        for fleet_id in faction.fleets:
            fleet = self.game_state.fleets.get(fleet_id)
            if not fleet or fleet.destination:
                continue
            
            # 查找敌对势力的星球
            enemy_planets = []
            for other_id, status in faction.diplomacy.items():
                if status in [DiplomacyStatus.HOSTILE, DiplomacyStatus.WAR]:
                    other_faction = self.game_state.factions[other_id]
                    enemy_planets.extend(other_faction.planets)
            
            if enemy_planets:
                # 移动到最近的敌对星球
                target = random.choice(enemy_planets)
                commands.append(Command(
                    faction_id=faction.id,
                    command_type=CommandType.MOVE,
                    parameters={"fleet": fleet_id, "destination": target}
                ))
                break
        
        return commands
    
    def _decide_diplomacy(self, faction: Faction) -> List[Command]:
        """决定外交行动"""
        commands = []
        
        # 基于声誉和实力决定外交策略
        for other_id, other_faction in self.game_state.factions.items():
            if other_id == faction.id:
                continue
            
            current_status = faction.diplomacy.get(other_id, DiplomacyStatus.NEUTRAL)
            
            # 随机进行外交行动
            if random.random() > 0.95:  # 低概率改变外交关系
                if current_status == DiplomacyStatus.NEUTRAL:
                    # 可能建立友好关系或敌对关系
                    if other_faction.reputation > 70:
                        new_status = DiplomacyStatus.FRIENDLY
                    elif other_faction.reputation < 30:
                        new_status = DiplomacyStatus.HOSTILE
                    else:
                        continue
                    
                    commands.append(Command(
                        faction_id=faction.id,
                        command_type=CommandType.DIPLOMACY,
                        parameters={
                            "target": other_id,
                            "action": "change_status",
                            "status": new_status.value
                        }
                    ))
                    break
        
        return commands
    
    def evaluate_threat(self, faction: Faction, other_id: str) -> float:
        """评估其他势力的威胁程度"""
        other_faction = self.game_state.factions[other_id]
        
        # 基于星球数量、舰队实力等评估威胁
        planet_score = len(other_faction.planets) * 10
        fleet_score = len(other_faction.fleets) * 20
        tech_score = len(other_faction.technologies) * 5
        
        threat = planet_score + fleet_score + tech_score
        
        # 考虑距离因素
        if faction.planets and other_faction.planets:
            min_distance = float('inf')
            for p1 in faction.planets:
                for p2 in other_faction.planets:
                    dist = self.galaxy_gen.get_distance(self.game_state, p1, p2)
                    if dist >= 0:
                        min_distance = min(min_distance, dist)
            
            # 距离越近威胁越大
            if min_distance < float('inf'):
                threat *= (10 / (min_distance + 1))
        
        return threat
