"""
回合结算引擎
处理回合中的所有事件和行动
"""
import random
from typing import Dict, List, Set
from game_engine import (
    GameState, Command, CommandType, Resources,
    BuildingType, DiplomacyStatus, Fleet,
    calculate_faction_power
)
from galaxy_generator import GalaxyGenerator


BUILDING_NAME_MAP = {
    BuildingType.ENERGY_PLANT: "能量工厂",
    BuildingType.MINING_STATION: "采矿站",
    BuildingType.RESEARCH_LAB: "研究实验室",
    BuildingType.SHIPYARD: "船坞",
    BuildingType.DEFENSE_STATION: "防御站"
}

DIPLOMACY_STATUS_MAP = {
    DiplomacyStatus.NEUTRAL: "中立",
    DiplomacyStatus.FRIENDLY: "友好",
    DiplomacyStatus.ALLIED: "结盟",
    DiplomacyStatus.HOSTILE: "敌对",
    DiplomacyStatus.WAR: "战争"
}


class TurnEngine:
    """回合结算引擎"""
    
    def __init__(self, game_state: GameState, galaxy_gen: GalaxyGenerator):
        self.game_state = game_state
        self.galaxy_gen = galaxy_gen
    
    def process_turn(self, commands: List[Command]):
        """处理回合"""
        # 若游戏已结束且未开启战后继续，则忽略本回合
        if self.game_state.game_over and not getattr(self.game_state, 'allow_postgame', False):
            self.game_state.add_event(
                "turn_ignored",
                None,
                "游戏已结束，回合请求被忽略"
            )
            return

        self.game_state.turn += 1
        # 每回合初始化殖民计数
        self.game_state.colonize_counts = {}
        
        # 1. 执行玩家和AI指令
        self._execute_commands(commands)
        
        # 2. 资源产出与运输
        self._process_resource_production()

        # 2.1 人口增长（能量工厂使人口每回合+1）
        self._process_population_growth()

        # 3. 刷新攻防能力
        self._refresh_military_capacity()

        # 4. 建造和研究进度
        self._process_research()

        # 5. 基于战争计划的地面争夺
        self._resolve_war_plans()

        # 6. 舰队移动
        self._process_fleet_movement()

        # 7. 战斗结算
        self._process_combat()

        # 8. 外交和声誉变化
        self._process_diplomacy()

        # 9. 事件生成
        self._process_events()
        
        # 10. 胜负判定（若开启战后继续，则依然可以更新最终分数，但不阻断后续回合）
        if not self.game_state.allow_postgame:
            self._check_victory_conditions()

        # 记录本回合各势力综合评分快照
        try:
            snapshot = {}
            for f_id, f in self.game_state.factions.items():
                snapshot[f_id] = calculate_faction_power(self.game_state, f)
            self.game_state.power_history.append(snapshot)
        except Exception:
            pass

        self.game_state.add_event(
            "turn_end",
            None,
            f"第 {self.game_state.turn} 回合结束"
        )

        # 围攻点数自然衰减：每回合每星球每进攻方 -1（最小为0），避免长期叠加过深
        try:
            for pid, mp in list(self.game_state.siege.items()):
                changed = False
                for aid, pts in list(mp.items()):
                    nv = max(0, int(pts) - 1)
                    if nv != pts:
                        mp[aid] = nv
                        changed = True
                # 清理全为0的条目
                if all(v == 0 for v in mp.values()):
                    self.game_state.siege.pop(pid, None)
                elif changed:
                    self.game_state.siege[pid] = {k: v for k, v in mp.items() if v > 0}
        except Exception:
            pass

        # 若本回合刚结束并产生胜者，再追加一条摘要事件
        if self.game_state.game_over and not self.game_state.allow_postgame:
            winner_name = None
            if self.game_state.winner and self.game_state.winner in self.game_state.factions:
                winner_name = self.game_state.factions[self.game_state.winner].name
            self.game_state.add_event(
                "game_over",
                self.game_state.winner,
                f"游戏结束：{winner_name or self.game_state.winner or '无'} 获胜（{self.game_state.end_reason}）",
                {"final_scores": self.game_state.final_scores}
            )
    
    def _execute_commands(self, commands: List[Command]):
        """执行指令"""
        colonize_batches: Dict[str, List[Command]] = {}

        for command in commands:
            try:
                if command.command_type == CommandType.COLONIZE:
                    to_planet = command.parameters.get("to_planet")
                    if to_planet:
                        colonize_batches.setdefault(to_planet, []).append(command)
                elif command.command_type == CommandType.BUILD:
                    self._execute_build(command)
                elif command.command_type == CommandType.MOVE:
                    self._execute_move(command)
                elif command.command_type == CommandType.RESEARCH:
                    self._execute_research(command)
                elif command.command_type == CommandType.DIPLOMACY:
                    self._execute_diplomacy(command)
                elif command.command_type == CommandType.STRATEGY:
                    self._execute_strategy(command)
            except Exception as e:
                self.game_state.add_event(
                    "command_failed",
                    command.faction_id,
                    f"指令执行失败: {str(e)}"
                )

        if colonize_batches:
            self._resolve_colonize_conflicts(colonize_batches)

    def _resolve_colonize_conflicts(self, batches: Dict[str, List[Command]]):
        """多个势力争夺同一殖民目标时的处理"""
        # 改为不消耗资源，按人口规则执行，且每势力每回合最多4次
        # 保留旧成本变量以便未来切换策略
        # cost = Resources(minerals=100, energy=50)

        for planet_id, command_list in batches.items():
            target = self.game_state.planets.get(planet_id)
            if not target or target.owner is not None:
                continue

            contenders = []
            for command in command_list:
                faction = self.game_state.factions.get(command.faction_id)
                if not faction:
                    continue

                from_planet = command.parameters.get("from_planet")
                if not from_planet or from_planet not in faction.planets:
                    continue

                connected = self.galaxy_gen.get_connected_planets(self.game_state, from_planet)
                if planet_id not in connected:
                    continue

                origin_planet = self.game_state.planets.get(from_planet)
                if not origin_planet:
                    continue
                # 殖民次数上限：每回合每势力<=4
                used = self.game_state.colonize_counts.get(faction.id, 0)
                if used >= 4:
                    self.game_state.add_event(
                        "colonization_failed",
                        faction.id,
                        f"{faction.name} 本回合殖民次数已达上限",
                        {"planet": planet_id}
                    )
                    continue
                # 人口消耗与最低线：来源星球至少保留10人口，殖民技术消耗3，否则10
                consume = 3 if 'tech_colonization' in faction.technologies else 10
                if origin_planet.population < (10 + consume):
                    self.game_state.add_event(
                        "colonization_failed",
                        faction.id,
                        f"{faction.name} 对 {target.name} 的殖民失败：来源星球人口不足",
                        {"planet": planet_id}
                    )
                    continue

                power = calculate_faction_power(self.game_state, faction)
                origin_population = origin_planet.population
                contenders.append((power, origin_population, faction, from_planet))

            if not contenders:
                continue

            contenders.sort(key=lambda item: (item[0], item[1]))
            winner_power, _, winner_faction, winner_from = contenders[-1]

            # 应用人口消耗与容量上限
            winner_origin = self.game_state.planets.get(winner_from)
            consume = 3 if 'tech_colonization' in winner_faction.technologies else 10
            if not winner_origin or winner_origin.population < (10 + consume):
                self.game_state.add_event(
                    "colonization_failed",
                    winner_faction.id,
                    f"{winner_faction.name} 对 {target.name} 的殖民失败：来源星球人口不足",
                    {"planet": planet_id}
                )
                continue

            target.owner = winner_faction.id
            # 殖民技术可使新殖民星球获得随机额外人口
            bonus_pop = __import__('random').randint(1, 5) if 'tech_colonization' in winner_faction.technologies else 0
            target.population = 10 + bonus_pop
            if planet_id not in winner_faction.planets:
                winner_faction.planets.append(planet_id)
            # 从来源星球扣人口（仍需至少保留10）
            winner_origin.population = max(10, winner_origin.population - consume)
            # 计数+1
            self.game_state.colonize_counts[winner_faction.id] = self.game_state.colonize_counts.get(winner_faction.id, 0) + 1

            self.game_state.add_event(
                "colonization",
                winner_faction.id,
                f"{winner_faction.name} 成功殖民了 {target.name}",
                {"planet": planet_id, "from": winner_from}
            )

            for _, _, faction, _ in contenders[:-1]:
                self.game_state.add_event(
                    "colonization_contested",
                    faction.id,
                    f"{faction.name} 在争夺 {target.name} 时不敌更强的势力",
                    {"planet": planet_id, "winner": winner_faction.id}
                )

    def _process_population_growth(self):
        """人口增长：能量与科技加速；能源建筑提供基础增长"""
        for planet in self.game_state.planets.values():
            if not planet.owner:
                continue
            faction = self.game_state.factions.get(planet.owner)
            if not faction:
                continue
            delta = 0
            # 能量工厂基础+1
            if any(b == BuildingType.ENERGY_PLANT for b in planet.buildings):
                delta += 1
            # 势力能量越多增长越快：每500能量+1，上限+3
            try:
                extra = min(3, int((faction.resources.energy or 0.0) // 500))
                delta += extra
            except Exception:
                pass
            # 聚变能源科技再+1
            if 'tech_power' in faction.technologies:
                delta += 1
            if delta > 0:
                planet.population += delta
    
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
        
        # 人口建造：需要有人口，消耗1人口，无需能量/矿物
        if planet.population <= 0:
            return
        planet.population -= 1
        
        # 建造成功
        planet.buildings.append(building_type)

        self.game_state.add_event(
            "construction",
            faction.id,
            f"{faction.name} 在 {planet.name} 建造了 {BUILDING_NAME_MAP.get(building_type, building_type.value)}",
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
            tech = self.game_state.technologies.get(tech_id)
            tech_name = tech.name if tech else tech_id

            self.game_state.add_event(
                "research_started",
                faction.id,
                f"{faction.name} 开始研究 {tech_name}",
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
                f"{faction.name} 与 {target_faction.name} 的关系变为 {DIPLOMACY_STATUS_MAP.get(new_status, new_status.value)}",
                {"target": target_id, "status": new_status.value}
            )

    def _execute_strategy(self, command: Command):
        """执行战争/防御计划指令"""
        faction = self.game_state.factions[command.faction_id]
        mode = command.parameters.get("mode", "peace")

        if mode == "attack":
            target_id = command.parameters.get("target")
            if target_id and target_id in self.game_state.factions and target_id != faction.id:
                faction.strategy_mode = "attack"
                faction.war_target = target_id
                faction.defense_focus = []
                self.game_state.add_event(
                    "strategy",
                    faction.id,
                    f"{faction.name} 计划对 {self.game_state.factions[target_id].name} 发动进攻",
                    {"target": target_id}
                )
        elif mode == "defend":
            # 简化为全局防御：无需选择具体星球，进入防御模式后，任意被攻打星球均可触发拦截（消耗一次防御次数）
            faction.strategy_mode = "defend"
            faction.war_target = None
            faction.defense_focus = []
            self.game_state.add_event(
                "strategy",
                faction.id,
                f"{faction.name} 进入全局防御模式（无需指定星球）",
                {"global_defense": True}
            )
        else:
            faction.strategy_mode = "peace"
            faction.war_target = None
            faction.defense_focus = []

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

            # 记录经济产出历史（折算分数）
            cfg = getattr(self.game_state, 'victory_config', {}) or {}
            weights = cfg.get('econ_weights', {"energy":1.0, "minerals":1.0, "research":1.0})
            econ_score = (
                total_production.energy * weights.get('energy', 1.0) +
                total_production.minerals * weights.get('minerals', 1.0) +
                total_production.research * weights.get('research', 1.0)
            )
            hist = self.game_state.econ_history.setdefault(faction.id, [])
            hist.append(econ_score)
    
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
                
                # 增加研究进度：矿物加速科研，研究资源次要加成，研究实验室提供固定加成
                lab_bonus = 0.0
                for pid in faction.planets:
                    p = self.game_state.planets.get(pid)
                    if p:
                        lab_bonus += sum(1 for b in p.buildings if b == BuildingType.RESEARCH_LAB) * 5.0
                research_speed = faction.resources.minerals * 0.02 + faction.resources.research * 0.05 + lab_bonus
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

                    # 科技胜：在研究完成时即时检测
                    self._check_tech_victory_on_research(faction)
            
            # 清理已完成的研究
            for tech_id in completed:
                del faction.research_progress[tech_id]

        # 研究阶段后，也可再做一次科技胜全局检查（以防漏判）
        self._check_tech_victory_global()

    def _refresh_military_capacity(self):
        """依据综合实力为各势力刷新本回合可用的攻防次数"""
        for faction in self.game_state.factions.values():
            power = calculate_faction_power(self.game_state, faction)
            base = 1 + max(0, self.game_state.turn // 5)
            bonus = int(power // 600)
            faction.attack_charges = max(1, min(6, base + bonus))

            defense_structures = 0
            for planet_id in faction.planets:
                planet = self.game_state.planets.get(planet_id)
                if not planet:
                    continue
                defense_structures += sum(1 for b in planet.buildings if b == BuildingType.DEFENSE_STATION)

            defense_bonus = defense_structures // 2
            faction.defense_charges = max(1, min(6, base + defense_bonus))

            # 移除已失去的重点星球
            faction.defense_focus = [p for p in faction.defense_focus if p in faction.planets]

    def _resolve_war_plans(self):
        """根据战争计划执行地面争夺"""
        # 停战期内不执行地面争夺
        if getattr(self.game_state, 'truce_until', 0) and __import__('time').time() < self.game_state.truce_until:
            return
        for faction in self.game_state.factions.values():
            if faction.strategy_mode != "attack" or not faction.war_target:
                continue
            if faction.attack_charges <= 0:
                continue

            target_faction = self.game_state.factions.get(faction.war_target)
            if not target_faction:
                continue

            attackable = self._get_attackable_planets(faction, target_faction)
            if not attackable:
                continue

            while faction.attack_charges > 0 and attackable:
                planet_id = self._select_attack_target(faction, target_faction, attackable)
                planet = self.game_state.planets.get(planet_id)
                if not planet:
                    attackable.discard(planet_id)
                    continue

                success = self._attempt_planet_capture(faction, target_faction, planet)
                faction.attack_charges -= 1

                if success:
                    attackable = self._get_attackable_planets(faction, target_faction)
                else:
                    self.game_state.add_event(
                        "defense_success",
                        target_faction.id,
                        f"{target_faction.name} 成功保卫了 {planet.name}",
                        {"planet": planet_id}
                    )

    def _get_attackable_planets(self, attacker, defender) -> Set[str]:
        """找到至少与进攻方星球相邻的敌方星球"""
        candidates = set()
        for planet_id in defender.planets:
            neighbors = self.galaxy_gen.get_connected_planets(self.game_state, planet_id)
            if any(n in attacker.planets for n in neighbors):
                candidates.add(planet_id)
        return candidates

    def _select_attack_target(self, attacker, defender, candidates: Set[str]) -> str:
        """选择攻击目标，优先缺乏防御的高价值星球"""
        best_id = None
        best_score = float('-inf')
        for planet_id in candidates:
            planet = self.game_state.planets.get(planet_id)
            if not planet:
                continue
            has_defense = any(b == BuildingType.DEFENSE_STATION for b in planet.buildings)
            focus_penalty = 30 if planet_id in defender.defense_focus else 0
            score = planet.population - (25 if has_defense else 0) - focus_penalty
            if score > best_score:
                best_score = score
                best_id = planet_id
        return best_id if best_id is not None else next(iter(candidates))

    def _attempt_planet_capture(self, attacker, defender, planet) -> bool:
        """尝试占领星球，成功返回 True，否则 False
        新规则：成功率依赖进攻/防御有效战力对比，而非固定概率。
        - 进攻有效战力 = 行星处进攻方舰船战力合计 × (1 + 熟练度修正 + 科技修正) × 邻接支援修正
        - 防御有效战力 = 星球驻军（舰队在该星球的战力） × (1 + 建筑/科技修正) × 围攻衰减修正 × 滩头保护修正
        - 成功概率 = attack_power^alpha / (attack_power^alpha + defense_power^alpha)，alpha 默认 1.1
        - 防御拦截（防御次数/防御站/科技/能量护盾）仍然优先于概率计算。
        - 围攻进度：每次强袭失败，对该(planet, attacker) 的 siege 点数+1，使防御系数按 1/(1+0.1*points) 衰减；一旦成功占领则清零。
        - 滩头保护：星球在被夺取后2回合内提供 1.2 的防御系数加成，避免立刻被反抢。
        """
        # 停战期禁止占领
        if getattr(self.game_state, 'truce_until', 0) and __import__('time').time() < self.game_state.truce_until:
            self.game_state.add_event(
                "truce_active",
                attacker.id,
                f"停战期内禁止对 {planet.name} 的占领行动",
                {"planet": planet.id}
            )
            return False
        # 滩头保护判定（前置，如果存在且还在保护期，直接增强后续防御计算）
        beachhead_mult = 1.0
        try:
            if getattr(planet, 'capture_protection_until_turn', 0) and self.game_state.turn < planet.capture_protection_until_turn:
                beachhead_mult = 1.2
        except Exception:
            pass
        defended = False
        # 若进攻方已无任何行星，但在该星球集结的己方舰船总数 > 10，则可发动背城一击（仍受护盾与停战限制）
        try:
            if len(attacker.planets) == 0:
                ships_here = self._count_faction_ships_on_planet(attacker.id, planet.id)
                threshold = int(getattr(self.game_state, 'rules', {}).get('desperate_capture_threshold', 10))
                if ships_here > threshold:
                    # 护盾最后再判定
                    if self._can_use_energy_shield(defender):
                        self.game_state.add_event(
                            "shield_defense",
                            defender.id,
                            f"{defender.name} 在 {planet.name} 启动能量护盾，抵御了背城一击",
                            {"planet": planet.id}
                        )
                        return False
                    planet.owner = attacker.id
                    if planet.id not in attacker.planets:
                        attacker.planets.append(planet.id)
                    # 从原拥有者剔除
                    if defender and planet.id in defender.planets:
                        defender.planets.remove(planet.id)
                    self.game_state.add_event(
                        "planet_captured",
                        attacker.id,
                        f"{attacker.name} 于绝境中集结舰队强夺 {planet.name}",
                        {"planet": planet.id, "ships_used": ships_here, "desperate": True, "threshold": threshold}
                    )
                    return True
        except Exception:
            pass

        # 多层防御判定：防御站、激光/FTL科技、能源护盾（终局科技，附加限制）
        if defender.strategy_mode == "defend" and defender.defense_charges > 0:
            defender.defense_charges -= 1
            defended = True
        # 若未启用防御模式，则防御设施可在有防御次数时提供一次拦截
        elif any(b == BuildingType.DEFENSE_STATION for b in planet.buildings) and defender.defense_charges > 0:
            defender.defense_charges -= 1
            defended = True

        # 若仍未被拦截，按设施与科技概率进行防御（基础格挡层）
        if not defended:
            # 防御站独立概率（30%）
            if any(b == BuildingType.DEFENSE_STATION for b in planet.buildings):
                if random.random() < 0.3:
                    defended = True
            # 科技：激光与FTL 各自 +15% 概率
            tech_bonus = 0.0
            if 'tech_laser' in defender.technologies:
                tech_bonus += 0.15
            if 'tech_ftl' in defender.technologies:
                tech_bonus += 0.15
            if not defended and tech_bonus > 0 and random.random() < tech_bonus:
                defended = True
            # 能量护盾：研究完成且满足“≤2星球或≥90%控图，并且开局满10分钟”方可触发一次性直接抵挡
            if not defended and self._can_use_energy_shield(defender):
                defended = True
                try:
                    self.game_state.add_event(
                        "shield_defense",
                        defender.id,
                        f"{defender.name} 动用能量护盾守住了 {planet.name}",
                        {"planet": planet.id}
                    )
                except Exception:
                    pass

        if defended:
            return False
        # 计算强袭成功概率：有效战力对比
        atk_power, def_power, details = self._calc_capture_effective_power(attacker, defender, planet, beachhead_mult)
        # 平滑指数
        alpha = 1.1
        prob = 0.0
        try:
            a = max(0.0, atk_power) ** alpha
            d = max(0.0, def_power) ** alpha
            if a + d > 0:
                prob = a / (a + d)
        except Exception:
            prob = 0.0

        roll = random.random()
        if roll < prob:
            # 占领成功
            defender.diplomacy[attacker.id] = DiplomacyStatus.WAR
            attacker.diplomacy[defender.id] = DiplomacyStatus.WAR

            if planet.owner == defender.id and planet.id in defender.planets:
                defender.planets.remove(planet.id)

            planet.owner = attacker.id
            planet.population = max(10, int(planet.population * 0.7))
            if planet.id not in attacker.planets:
                attacker.planets.append(planet.id)

            # 设置滩头保护：2回合
            try:
                planet.capture_protection_until_turn = self.game_state.turn + 2
            except Exception:
                pass

            # 清理围攻进度
            try:
                if planet.id in self.game_state.siege:
                    self.game_state.siege.pop(planet.id, None)
            except Exception:
                pass

            self.game_state.add_event(
                "planet_conquered",
                attacker.id,
                f"{attacker.name} 占领了 {planet.name}",
                {"planet": planet.id, "from": defender.id, "capture": {"attack_power": atk_power, "defense_power": def_power, "prob": prob}}
            )
            return True
        else:
            # 占领失败：累积围攻点数
            try:
                node = self.game_state.siege.setdefault(planet.id, {})
                node[attacker.id] = node.get(attacker.id, 0) + 1
            except Exception:
                pass
            self.game_state.add_event(
                "defense_success",
                defender.id,
                f"{defender.name} 守住了 {planet.name}",
                {"planet": planet.id, "capture": {"attack_power": atk_power, "defense_power": def_power, "prob": prob, "roll": roll}}
            )
            return False

    def _calc_capture_effective_power(self, attacker, defender, planet, beachhead_mult: float = 1.0):
        """计算强袭的进攻/防御有效战力，返回 (atk_power, def_power, details)"""
        # 进攻：本星球处的进攻方舰队战力合计
        atk_raw = 0.0
        avg_prof = 0.0
        prof_samples = 0
        for fl in self.game_state.fleets.values():
            if fl.owner == attacker.id and fl.position == planet.id:
                s = fl.get_strength()
                atk_raw += s
                try:
                    avg_prof += (getattr(fl, 'proficiency', 0.0) or 0.0)
                    prof_samples += 1
                except Exception:
                    pass
        avg_prof = (avg_prof / prof_samples) if prof_samples > 0 else 0.0
        # 熟练度修正：最多+10%
        prof_mult = 1.0 + max(-0.1, min(0.1, avg_prof / 100.0))
        # 科技修正：激光 +10%，FTL +5%
        tech_mult_atk = 1.0
        if 'tech_laser' in attacker.technologies:
            tech_mult_atk += 0.10
        if 'tech_ftl' in attacker.technologies:
            tech_mult_atk += 0.05
        # 邻接支援：与本星球相邻的己方星球数量 * 3%（最多 +12%）
        try:
            neighbors = self.galaxy_gen.get_connected_planets(self.game_state, planet.id)
            adj_own = sum(1 for n in neighbors if n in attacker.planets)
            adj_mult = 1.0 + min(0.12, adj_own * 0.03)
        except Exception:
            adj_mult = 1.0
        atk_power = atk_raw * prof_mult * tech_mult_atk * adj_mult

        # 防御：本星球处的防守方舰队战力合计
        def_raw = 0.0
        for fl in self.game_state.fleets.values():
            if fl.owner == defender.id and fl.position == planet.id:
                def_raw += fl.get_strength()
        # 建筑/科技修正：防御站 +20%，激光 +10%，FTL +5%
        def_mult = 1.0
        if any(b == BuildingType.DEFENSE_STATION for b in planet.buildings):
            def_mult += 0.20
        if 'tech_laser' in defender.technologies:
            def_mult += 0.10
        if 'tech_ftl' in defender.technologies:
            def_mult += 0.05
        # 围攻衰减：针对该进攻方的点数，每点 -10%（按 1/(1+0.1*points) 衰减，最多减到 40%）
        siege_mult = 1.0
        try:
            pts = (self.game_state.siege.get(planet.id, {}) or {}).get(attacker.id, 0)
            siege_mult = max(0.4, 1.0 / (1.0 + 0.1 * float(pts)))
        except Exception:
            siege_mult = 1.0
        def_power = def_raw * def_mult * siege_mult * beachhead_mult

        details = {
            "atk": {"raw": atk_raw, "prof_mult": prof_mult, "tech_mult": tech_mult_atk, "adj_mult": adj_mult},
            "def": {"raw": def_raw, "def_mult": def_mult, "siege_mult": siege_mult, "beachhead_mult": beachhead_mult}
        }
        return atk_power, def_power, details

    def _can_use_energy_shield(self, defender) -> bool:
        """判断能量护盾是否可用于本次防御。
        需求：
        - 已研究 tech_shields
        - 距离开局 ≥ 600 秒
        - 满足 (己方星球数 ≤ 2) 或者 (控图比例 ≥ 90%)
        """
        try:
            if 'tech_shields' not in defender.technologies:
                return False
            import time as _t
            start = float(getattr(self.game_state, 'game_start_time', 0.0) or 0.0)
            if start <= 0 or (_t.time() - start) < 600.0:
                return False
            total = max(1, len(self.game_state.planets))
            own = len(defender.planets)
            if own <= 2:
                return True
            ratio = own / float(total)
            return ratio >= 0.9
        except Exception:
            return False
    
    def _count_faction_ships_on_planet(self, faction_id: str, planet_id: str) -> int:
        """统计某势力在某星球处所有舰队的舰船总数（按艘数计）。"""
        total = 0
        for fl in self.game_state.fleets.values():
            if fl.owner == faction_id and fl.position == planet_id:
                try:
                    total += sum(int(v) for v in (fl.ships or {}).values())
                except Exception:
                    for v in (fl.ships or {}).values():
                        try:
                            total += int(v)
                        except Exception:
                            pass
        return total

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
            
            # 巡逻拦截：若本次移动跨越的边 (position,destination) 有敌方巡逻舰队，则按概率拦截
            crossing = tuple(sorted([fleet.position, fleet.destination]))
            interceptors = []
            for other in self.game_state.fleets.values():
                if other.owner == fleet.owner:
                    continue
                if other.patrol_edge == crossing:
                    interceptors.append(other)
            if interceptors:
                total_strength = sum(i.get_strength() for i in interceptors)
                prob = min(1.0, total_strength * 0.02)
                if random.random() < prob:
                    # 被拦截：取消此次移动（保留目的地以便下回合可重试，或清空？此处选择清空避免卡死）
                    self.game_state.add_event(
                        "fleet_intercepted",
                        fleet.owner,
                        f"{self.game_state.factions.get(fleet.owner).name if fleet.owner in self.game_state.factions else fleet.owner} 的舰队在连线被巡逻拦截",
                        {"fleet": fleet.id, "edge": list(crossing), "prob": prob}
                    )
                    fleet.destination = None
                    fleet.travel_progress = 0.0
                    continue

            # 增加移动进度
            fleet.travel_progress += 1.0 / distance
            
            # 检查是否到达
            if fleet.travel_progress >= 1.0:
                fleet.position = fleet.destination
                fleet.destination = None
                fleet.travel_progress = 0.0
                # 抵达微量成长
                try:
                    fleet.proficiency = min(100.0, (getattr(fleet, 'proficiency', 0.0) or 0.0) + 0.5)
                except Exception:
                    pass
                
                self.game_state.add_event(
                    "fleet_arrived",
                    fleet.owner,
                    f"舰队到达 {self.game_state.planets[fleet.position].name}",
                    {"fleet": fleet.id, "planet": fleet.position}
                )
                # 抵达后：检查驻扎上限（基础5，船坞每个+2）。若势力目前无行星，则放宽此限制，允许堆叠以利于强袭玩法。
                pid = fleet.position
                count_here = sum(1 for f in self.game_state.fleets.values() if f.position == pid)
                cap = self._get_garrison_cap(pid)
                try:
                    owner_f = self.game_state.factions.get(fleet.owner)
                    if owner_f and len(owner_f.planets) == 0:
                        cap = max(cap, count_here)  # 实际上等于放开
                except Exception:
                    pass
                if count_here > cap:
                    # 超限则回退至之前星球（简单处理：保持在原地，不算到达）
                    # 这里无法得知之前位置，简化为随机遣返一支非玩家舰队以维持上限
                    overflow = [f for f in self.game_state.fleets.values() if f.position == pid]
                    if overflow:
                        kicked = overflow[0]
                        self.game_state.add_event(
                            "garrison_overflow",
                            kicked.owner,
                            f"{self.game_state.planets[pid].name} 驻扎舰队超限，自动疏散一支舰队",
                            {"planet": pid, "fleet": kicked.id}
                        )
                        # 将其取消到达：随机选择邻星（若无邻居则原地保留但标注）
                        neighbors = self.galaxy_gen.get_connected_planets(self.game_state, pid) or []
                        if neighbors:
                            kicked.position = neighbors[0]
                        # 若没有邻居则不处理（图极端情况）
    
    def _get_garrison_cap(self, planet_id: str) -> int:
        """驻扎上限：基础5，每个船坞+2"""
        p = self.game_state.planets.get(planet_id)
        if not p:
            return 5
        shipyards = sum(1 for b in p.buildings if b == BuildingType.SHIPYARD)
        return 5 + shipyards * 2

        #（调整）无星球势力保留舰队指挥权：不再自动将其舰队设为无主
        # 收编
        for fid, fl in self.game_state.fleets.items():
            if fl.owner is not None:
                continue
            pid = fl.position
            # 若星球有所有者，则归属给该势力
            planet = self.game_state.planets.get(pid)
            candidates = set()
            if planet and planet.owner:
                candidates.add(planet.owner)
            # 若同位置有任意势力舰队，则加入候选
            co_located = [ofl for ofl in self.game_state.fleets.values() if ofl.owner and ofl.position == pid]
            for ofl in co_located:
                candidates.add(ofl.owner)
            if candidates:
                # 选择综合实力最高的势力收编
                best = None
                best_score = float('-inf')
                for oid in candidates:
                    f = self.game_state.factions.get(oid)
                    if not f:
                        continue
                    score = calculate_faction_power(self.game_state, f)
                    if score > best_score:
                        best_score = score
                        best = oid
                if best:
                    fl.owner = best
                    if fid not in self.game_state.factions[best].fleets:
                        self.game_state.factions[best].fleets.append(fid)
                    pname = self.game_state.planets.get(pid).name if self.game_state.planets.get(pid) else pid
                    self.game_state.add_event("fleet_captured", best, f"在 {pname} 收编了无主舰队", {"fleet": fid, "planet": pid, "from": getattr(fl, 'exiled_from', None)})
    
    def _process_combat(self):
        """处理战斗"""
        # 停战期内不触发舰队战斗
        if getattr(self.game_state, 'truce_until', 0) and __import__('time').time() < self.game_state.truce_until:
            return
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
                    
                    status = faction1.diplomacy.get(fleet2.owner, DiplomacyStatus.NEUTRAL)
                    if status in [DiplomacyStatus.HOSTILE, DiplomacyStatus.WAR]:
                        self._resolve_combat(fleet1, fleet2, planet_id)
    
    def _resolve_combat(self, fleet1: Fleet, fleet2: Fleet, planet_id: str):
        """解决战斗"""
        strength1 = fleet1.get_strength()
        strength2 = fleet2.get_strength()
        # 熟练度提供最多±10%的修正
        try:
            p1 = getattr(fleet1, 'proficiency', 0.0) or 0.0
            p2 = getattr(fleet2, 'proficiency', 0.0) or 0.0
            strength1 *= (1.0 + max(-0.1, min(0.1, p1 / 100.0)))
            strength2 *= (1.0 + max(-0.1, min(0.1, p2 / 100.0)))
        except Exception:
            pass
        
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
        # 参与战斗后熟练度提升
        try:
            fleet1.proficiency = min(100.0, (getattr(fleet1, 'proficiency', 0.0) or 0.0) + 1.5)
            fleet2.proficiency = min(100.0, (getattr(fleet2, 'proficiency', 0.0) or 0.0) + 1.0)
        except Exception:
            pass
        
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

    def _check_victory_conditions(self):
        """检查并设置胜负状态"""
        if self.game_state.game_over:
            return

        # 停战期内，所有胜利条件暂不生效（仅可展示进度，不触发 game_over）
        try:
            import time as _t
            if getattr(self.game_state, 'truce_until', 0) and _t.time() < self.game_state.truce_until:
                return
        except Exception:
            pass

        # 1) 统治胜利：单一势力占领全部可殖民星球
        owners = [p.owner for p in self.game_state.planets.values() if p.owner is not None]
        unique_owners = set(owners)
        if len(owners) > 0 and len(unique_owners) == 1:
            self.game_state.game_over = True
        #（调整）无星球势力保留舰队指挥权：不再自动将其舰队设为无主
        # 仍然保留对“确实存在的无主舰队”的收编逻辑（例如未来事件生成的无人舰队）
            self.game_state.final_scores = self._calc_all_scores()
            return

        # 3) 回合上限：比较综合实力得分
        if self.game_state.turn >= getattr(self.game_state, 'max_turns', 200):
            scores = self._calc_all_scores()
            self.game_state.final_scores = scores
            # 最高分为胜
            if scores:
                winner = max(scores.items(), key=lambda kv: kv[1])[0]
                self.game_state.winner = winner
                self.game_state.end_reason = f"回合上限（{self.game_state.turn}/{self.game_state.max_turns}），综合实力最高"
                self.game_state.game_over = True

        # 4) 经济胜（已停用）：胜利仅依据综合评价（回合上限）或一统/淘汰
        # if not self.game_state.game_over:
        #     self._check_economic_victory()

    def _calc_all_scores(self) -> Dict[str, float]:
        """计算所有势力的综合实力分数"""
        scores: Dict[str, float] = {}
        for f_id, faction in self.game_state.factions.items():
            scores[f_id] = calculate_faction_power(self.game_state, faction)
        return scores

    def _check_tech_victory_on_research(self, faction):
        cfg = getattr(self.game_state, 'victory_config', {}) or {}
        if not cfg.get('tech_victory_enabled', False) or self.game_state.game_over:
            return
        # 停战期内不结算科技胜
        try:
            import time as _t
            if getattr(self.game_state, 'truce_until', 0) and _t.time() < self.game_state.truce_until:
                return
        except Exception:
            pass
        required_ids = set(cfg.get('tech_required_ids', []))
        threshold = float(cfg.get('tech_score_threshold', 0.0) or 0.0)

        # 途径1：完成指定科技集合
        if required_ids and required_ids.issubset(set(faction.technologies)):
            self.game_state.game_over = True
            self.game_state.winner = faction.id
            self.game_state.end_reason = "科技胜：完成关键科技"
            self.game_state.final_scores = self._calc_all_scores()
            return

        # 途径2：累计完成科技的成本总和达到阈值
        if threshold > 0:
            total_cost = 0.0
            for tid in faction.technologies:
                t = self.game_state.technologies.get(tid)
                if t:
                    total_cost += t.cost
            if total_cost >= threshold:
                self.game_state.game_over = True
                self.game_state.winner = faction.id
                self.game_state.end_reason = f"科技胜：累计科技成本≥{threshold}"
                self.game_state.final_scores = self._calc_all_scores()

    def _check_tech_victory_global(self):
        cfg = getattr(self.game_state, 'victory_config', {}) or {}
        if not cfg.get('tech_victory_enabled', False) or self.game_state.game_over:
            return
        # 停战期内不结算科技胜
        try:
            import time as _t
            if getattr(self.game_state, 'truce_until', 0) and _t.time() < self.game_state.truce_until:
                return
        except Exception:
            pass
        required_ids = set(cfg.get('tech_required_ids', []))
        threshold = float(cfg.get('tech_score_threshold', 0.0) or 0.0)

        for faction in self.game_state.factions.values():
            if self.game_state.game_over:
                break
            # 与 on_research 同逻辑，防漏
            if required_ids and required_ids.issubset(set(faction.technologies)):
                self.game_state.game_over = True
                self.game_state.winner = faction.id
                self.game_state.end_reason = "科技胜：完成关键科技"
                self.game_state.final_scores = self._calc_all_scores()
                break
            if threshold > 0:
                total_cost = 0.0
                for tid in faction.technologies:
                    t = self.game_state.technologies.get(tid)
                    if t:
                        total_cost += t.cost
                if total_cost >= threshold:
                    self.game_state.game_over = True
                    self.game_state.winner = faction.id
                    self.game_state.end_reason = f"科技胜：累计科技成本≥{threshold}"
                    self.game_state.final_scores = self._calc_all_scores()
                    break

    def _check_economic_victory(self):
        cfg = getattr(self.game_state, 'victory_config', {}) or {}
        if not cfg.get('econ_victory_enabled', False):
            return
        if self.game_state.game_over:
            return
        # 停战期内不结算经济胜
        try:
            import time as _t
            if getattr(self.game_state, 'truce_until', 0) and _t.time() < self.game_state.truce_until:
                return
        except Exception:
            pass
        window = int(cfg.get('econ_window', 3) or 3)
        threshold = float(cfg.get('econ_threshold', 0.0) or 0.0)

        # 任一势力在最近 window 个回合里，每回合 econ 分数均≥阈值，且均为当回合第一
        # 由于我们在回合末判定，此时本回合分数已记录在 econ_history
        # 先计算每回合的领先者
        # 取所有势力历史长度最短的前缀可用作最大可比较回合数
        # 我们只对最近 window 回合进行验证

        # 若回合数不足，直接返回
        if self.game_state.turn < window:
            return

        # 按势力截取最近 window 回合
        recent_scores: Dict[str, List[float]] = {}
        for fid, hist in self.game_state.econ_history.items():
            if len(hist) < window:
                return  # 有势力样本不足，暂不判定
            recent_scores[fid] = hist[-window:]

        # 对 recent 的每个回合，找出领先者（可能并列）
        # 然后检查是否存在某势力在每个回合：分数≥阈值且在领先组
        for fid, seq in recent_scores.items():
            satisfied_all = True
            for i in range(window):
                turn_i_scores = [recent_scores[ofid][i] for ofid in recent_scores.keys()]
                max_i = max(turn_i_scores)
                if not (seq[i] >= threshold and abs(seq[i] - max_i) < 1e-6 or seq[i] == max_i):
                    # 不满足当回合领先且达标
                    satisfied_all = False
                    break
            if satisfied_all:
                self.game_state.game_over = True
                self.game_state.winner = fid
                self.game_state.end_reason = f"经济胜：连续{window}回合产出领先且≥{threshold}"
                self.game_state.final_scores = self._calc_all_scores()
                break
