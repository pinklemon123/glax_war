"""
回合结算引擎
处理回合中的所有事件和行动
"""
import random
from typing import List
from game_engine import (
    GameState, Command, CommandType, Resources,
    BuildingType, ShipType, DiplomacyStatus, Fleet, Technology
)
from galaxy_generator import GalaxyGenerator


class TurnEngine:
    """回合结算引擎"""
    
    def __init__(self, game_state: GameState, galaxy_gen: GalaxyGenerator):
        self.game_state = game_state
        self.galaxy_gen = galaxy_gen
    
    def process_turn(self, commands: List[Command]):
        """处理回合"""
        self.game_state.turn += 1
        
        # 1. 执行玩家和AI指令
        self._execute_commands(commands)
        
        # 2. 资源产出与运输
        self._process_resource_production()
        
        # 3. 建造和研究进度
        self._process_research()
        
        # 4. 舰队移动
        self._process_fleet_movement()
        
        # 5. 战斗结算
        self._process_combat()
        
        # 6. 外交和声誉变化
        self._process_diplomacy()
        
        # 7. 事件生成
        self._process_events()
        
        self.game_state.add_event(
            "turn_end",
            None,
            f"第 {self.game_state.turn} 回合结束"
        )
    
    def _execute_commands(self, commands: List[Command]):
        """执行指令"""
        for command in commands:
            try:
                if command.command_type == CommandType.COLONIZE:
                    self._execute_colonize(command)
                elif command.command_type == CommandType.BUILD:
                    self._execute_build(command)
                elif command.command_type == CommandType.MOVE:
                    self._execute_move(command)
                elif command.command_type == CommandType.RESEARCH:
                    self._execute_research(command)
                elif command.command_type == CommandType.DIPLOMACY:
                    self._execute_diplomacy(command)
            except Exception as e:
                self.game_state.add_event(
                    "command_failed",
                    command.faction_id,
                    f"指令执行失败: {str(e)}"
                )
    
    def _execute_colonize(self, command: Command):
        """执行殖民指令"""
        faction = self.game_state.factions[command.faction_id]
        from_planet = command.parameters["from_planet"]
        to_planet = command.parameters["to_planet"]
        
        target = self.game_state.planets[to_planet]
        
        # 检查星球是否已被占领
        if target.owner is not None:
            return
        
        # 检查是否相邻
        connected = self.galaxy_gen.get_connected_planets(self.game_state, from_planet)
        if to_planet not in connected:
            return
        
        # 消耗资源
        cost = Resources(minerals=100, energy=50)
        if not faction.resources.subtract(cost):
            return
        
        # 殖民成功
        target.owner = faction.id
        target.population = 10
        faction.planets.append(to_planet)
        
        self.game_state.add_event(
            "colonization",
            faction.id,
            f"{faction.name} 殖民了 {target.name}",
            {"planet": to_planet}
        )
    
    def _execute_build(self, command: Command):
        """执行建造指令"""
        faction = self.game_state.factions[command.faction_id]
        planet_id = command.parameters["planet"]
        building_type = BuildingType(command.parameters["building"])
        
        planet = self.game_state.planets[planet_id]
        
        # 检查星球所有权
        if planet.owner != faction.id:
            return
        
        # 检查建筑数量限制
        if len(planet.buildings) >= 5:
            return
        
        # 消耗资源
        cost = Resources(minerals=50, energy=50)
        if not faction.resources.subtract(cost):
            return
        
        # 建造成功
        planet.buildings.append(building_type)
        
        self.game_state.add_event(
            "construction",
            faction.id,
            f"{faction.name} 在 {planet.name} 建造了 {building_type.value}",
            {"planet": planet_id, "building": building_type.value}
        )
    
    def _execute_move(self, command: Command):
        """执行移动指令"""
        faction = self.game_state.factions[command.faction_id]
        fleet_id = command.parameters["fleet"]
        destination = command.parameters["destination"]
        
        fleet = self.game_state.fleets.get(fleet_id)
        if not fleet or fleet.owner != faction.id:
            return
        
        # 设置目的地
        fleet.destination = destination
        fleet.travel_progress = 0.0
        
        self.game_state.add_event(
            "fleet_movement",
            faction.id,
            f"{faction.name} 的舰队向 {self.game_state.planets[destination].name} 移动",
            {"fleet": fleet_id, "destination": destination}
        )
    
    def _execute_research(self, command: Command):
        """执行研究指令"""
        faction = self.game_state.factions[command.faction_id]
        tech_id = command.parameters["technology"]
        
        # 初始化研究进度
        if tech_id not in faction.research_progress:
            faction.research_progress[tech_id] = 0.0
            
            self.game_state.add_event(
                "research_started",
                faction.id,
                f"{faction.name} 开始研究 {tech_id}",
                {"technology": tech_id}
            )
    
    def _execute_diplomacy(self, command: Command):
        """执行外交指令"""
        faction = self.game_state.factions[command.faction_id]
        target_id = command.parameters["target"]
        action = command.parameters["action"]
        
        if action == "change_status":
            new_status = DiplomacyStatus(command.parameters["status"])
            old_status = faction.diplomacy.get(target_id, DiplomacyStatus.NEUTRAL)
            
            # 背叛惩罚
            if old_status == DiplomacyStatus.ALLIED and new_status in [DiplomacyStatus.HOSTILE, DiplomacyStatus.WAR]:
                faction.reputation -= 30
                self.game_state.add_event(
                    "betrayal",
                    faction.id,
                    f"{faction.name} 背叛了盟友，声誉下降",
                    {"target": target_id, "reputation_loss": 30}
                )
            
            faction.diplomacy[target_id] = new_status
            
            # 互相改变状态
            target_faction = self.game_state.factions[target_id]
            target_faction.diplomacy[faction.id] = new_status
            
            self.game_state.add_event(
                "diplomacy",
                faction.id,
                f"{faction.name} 与 {target_faction.name} 的关系变为 {new_status.value}",
                {"target": target_id, "status": new_status.value}
            )
    
    def _process_resource_production(self):
        """处理资源产出"""
        for faction in self.game_state.factions.values():
            total_production = Resources()
            
            for planet_id in faction.planets:
                planet = self.game_state.planets[planet_id]
                production = planet.calculate_production()
                planet.resource_production = production
                total_production.add(production)
            
            faction.resources.add(total_production)
    
    def _process_research(self):
        """处理研究进度"""
        for faction in self.game_state.factions.values():
            # 为所有进行中的研究增加进度
            completed = []
            for tech_id, progress in faction.research_progress.items():
                if tech_id in faction.technologies:
                    continue
                
                tech = self.game_state.technologies.get(tech_id)
                if not tech:
                    continue
                
                # 增加研究进度
                research_speed = faction.resources.research * 0.1
                faction.research_progress[tech_id] += research_speed
                
                # 检查是否完成
                if faction.research_progress[tech_id] >= tech.cost:
                    completed.append(tech_id)
                    faction.technologies.append(tech_id)
                    
                    self.game_state.add_event(
                        "research_completed",
                        faction.id,
                        f"{faction.name} 完成了 {tech.name} 的研究",
                        {"technology": tech_id}
                    )
            
            # 清理已完成的研究
            for tech_id in completed:
                del faction.research_progress[tech_id]
    
    def _process_fleet_movement(self):
        """处理舰队移动"""
        for fleet in self.game_state.fleets.values():
            if not fleet.destination:
                continue
            
            # 计算距离
            distance = self.galaxy_gen.get_distance(
                self.game_state, 
                fleet.position, 
                fleet.destination
            )
            
            if distance <= 0:
                continue
            
            # 增加移动进度
            fleet.travel_progress += 1.0 / distance
            
            # 检查是否到达
            if fleet.travel_progress >= 1.0:
                fleet.position = fleet.destination
                fleet.destination = None
                fleet.travel_progress = 0.0
                
                self.game_state.add_event(
                    "fleet_arrived",
                    fleet.owner,
                    f"舰队到达 {self.game_state.planets[fleet.position].name}",
                    {"fleet": fleet.id, "planet": fleet.position}
                )
    
    def _process_combat(self):
        """处理战斗"""
        # 查找同一位置的敌对舰队
        planet_fleets = {}
        for fleet in self.game_state.fleets.values():
            if fleet.position not in planet_fleets:
                planet_fleets[fleet.position] = []
            planet_fleets[fleet.position].append(fleet)
        
        for planet_id, fleets in planet_fleets.items():
            if len(fleets) < 2:
                continue
            
            # 检查是否有敌对关系
            for i, fleet1 in enumerate(fleets):
                for fleet2 in fleets[i+1:]:
                    faction1 = self.game_state.factions[fleet1.owner]
                    faction2 = self.game_state.factions[fleet2.owner]
                    
                    status = faction1.diplomacy.get(fleet2.owner, DiplomacyStatus.NEUTRAL)
                    if status in [DiplomacyStatus.HOSTILE, DiplomacyStatus.WAR]:
                        self._resolve_combat(fleet1, fleet2, planet_id)
    
    def _resolve_combat(self, fleet1: Fleet, fleet2: Fleet, planet_id: str):
        """解决战斗"""
        strength1 = fleet1.get_strength()
        strength2 = fleet2.get_strength()
        
        # 简单的战斗模型
        total = strength1 + strength2
        if total == 0:
            return
        
        # 双方都受损
        damage_ratio1 = strength2 / total
        damage_ratio2 = strength1 / total
        
        # 减少舰船数量
        for ship_type in fleet1.ships:
            losses = int(fleet1.ships[ship_type] * damage_ratio1 * 0.5)
            fleet1.ships[ship_type] = max(0, fleet1.ships[ship_type] - losses)
        
        for ship_type in fleet2.ships:
            losses = int(fleet2.ships[ship_type] * damage_ratio2 * 0.5)
            fleet2.ships[ship_type] = max(0, fleet2.ships[ship_type] - losses)
        
        winner = fleet1.owner if strength1 > strength2 else fleet2.owner
        
        self.game_state.add_event(
            "combat",
            None,
            f"在 {self.game_state.planets[planet_id].name} 发生战斗",
            {
                "planet": planet_id,
                "fleet1": fleet1.id,
                "fleet2": fleet2.id,
                "winner": winner
            }
        )
    
    def _process_diplomacy(self):
        """处理外交变化"""
        # 声誉自然恢复
        for faction in self.game_state.factions.values():
            if faction.reputation < 100:
                faction.reputation = min(100, faction.reputation + 1)
    
    def _process_events(self):
        """处理随机事件"""
        # 低概率触发随机事件
        if random.random() > 0.9:
            event_types = ["遗迹发现", "太空风暴", "外交使节", "海盗袭击"]
            event_type = random.choice(event_types)
            
            # 随机选择一个势力
            if self.game_state.factions:
                faction = random.choice(list(self.game_state.factions.values()))
                
                self.game_state.add_event(
                    "random_event",
                    faction.id,
                    f"{faction.name} 遭遇了 {event_type}",
                    {"event_type": event_type}
                )
