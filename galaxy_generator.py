"""
星系地图生成器
使用网络图算法生成星系
"""
import random
import networkx as nx
from typing import List, Tuple
from game_engine import Planet, PlanetType, GameState


class GalaxyGenerator:
    """星系生成器"""
    
    def __init__(self, num_planets: int = 30, seed: int = None):
        self.num_planets = num_planets
        self.seed = seed
        if seed:
            random.seed(seed)
    
    def generate(self) -> GameState:
        """生成星系地图"""
        game_state = GameState()
        
        # 生成网络图
        graph = self._generate_graph()
        
        # 为每个节点创建星球
        planet_names = self._generate_planet_names()
        positions = nx.spring_layout(graph, seed=self.seed, k=2, iterations=50)
        
        for i, node in enumerate(graph.nodes()):
            planet_id = f"planet_{i}"
            planet_type = random.choice(list(PlanetType))
            
            # 转换位置坐标到合适的范围
            pos = positions[node]
            position = (int(pos[0] * 1000), int(pos[1] * 1000))
            
            planet = Planet(
                id=planet_id,
                name=planet_names[i],
                type=planet_type,
                position=position
            )
            game_state.planets[planet_id] = planet
        
        # 保存星球连接关系
        planet_list = list(game_state.planets.keys())
        for edge in graph.edges():
            game_state.connections.append((planet_list[edge[0]], planet_list[edge[1]]))
        
        return game_state
    
    def _generate_graph(self) -> nx.Graph:
        """生成网络图结构"""
        # 使用随机几何图或小世界网络
        if random.random() > 0.5:
            # 随机几何图 - 节点在空间中随机分布，距离近的连接
            graph = nx.random_geometric_graph(self.num_planets, 0.3, seed=self.seed)
        else:
            # Watts-Strogatz小世界网络
            k = max(4, self.num_planets // 10)  # 每个节点的邻居数
            p = 0.1  # 重连概率
            graph = nx.watts_strogatz_graph(self.num_planets, k, p, seed=self.seed)
        
        # 确保图是连通的
        if not nx.is_connected(graph):
            # 连接所有连通分量
            components = list(nx.connected_components(graph))
            for i in range(len(components) - 1):
                node1 = random.choice(list(components[i]))
                node2 = random.choice(list(components[i + 1]))
                graph.add_edge(node1, node2)
        
        return graph
    
    def _generate_planet_names(self) -> List[str]:
        """生成星球名称"""
        prefixes = [
            "Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta",
            "Nova", "Prime", "Centauri", "Proxima", "Vega", "Sirius", "Rigel",
            "Kepler", "Gliese", "Ross", "Wolf", "Tau", "Sigma", "Omega"
        ]
        
        suffixes = [
            "I", "II", "III", "IV", "V", "Prime", "Minor", "Major",
            "A", "B", "C", "D", "E"
        ]
        
        names = []
        used_names = set()
        
        for i in range(self.num_planets):
            while True:
                prefix = random.choice(prefixes)
                suffix = random.choice(suffixes)
                name = f"{prefix} {suffix}"
                
                if name not in used_names:
                    used_names.add(name)
                    names.append(name)
                    break
        
        return names
    
    def get_connected_planets(self, game_state: GameState, planet_id: str) -> List[str]:
        """获取与指定星球相连的星球列表"""
        connected = []
        for conn in game_state.connections:
            if conn[0] == planet_id:
                connected.append(conn[1])
            elif conn[1] == planet_id:
                connected.append(conn[0])
        return connected
    
    def get_distance(self, game_state: GameState, planet_id1: str, planet_id2: str) -> int:
        """计算两个星球之间的最短距离（跳跃次数）"""
        # 构建图
        graph = nx.Graph()
        for conn in game_state.connections:
            graph.add_edge(conn[0], conn[1])
        
        try:
            return nx.shortest_path_length(graph, planet_id1, planet_id2)
        except nx.NetworkXNoPath:
            return -1  # 不可达
