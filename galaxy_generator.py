"""
星系地图生成器
使用网络图算法生成星系
"""
import random
import networkx as nx
from typing import List, Tuple, Dict
from game_engine import Planet, PlanetType, GameState


class GalaxyGenerator:
    """星系生成器"""
    
    def __init__(self, num_planets: int = 30, seed: int = None):
        self.num_planets = num_planets
        self.seed = seed
        if seed:
            random.seed(seed)
        # 记录每个星球的簇标签（在 generate_clustered 中填充）
        self.cluster_labels: Dict[str, int] = {}
    
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

    def generate_clustered(self, num_clusters: int) -> GameState:
        """按簇生成星系，每个簇供一个势力前期发展。
        - 将所有行星分成 num_clusters 个簇，在圆周上布置簇中心。
        - 簇内使用近邻连接，簇间添加少量桥接边，保证可达。
        """
        game_state = GameState()
        self.cluster_labels.clear()

        # 生成簇中心（圆周）
        radius = 700
        centers: List[Tuple[float, float]] = []
        for i in range(num_clusters):
            angle = 2 * 3.1415926 * i / max(1, num_clusters)
            cx = radius * (1.0 * (random.random()*0.05 + 0.95)) * (1 if num_clusters == 1 else 1) * (1)
            cy = radius * (1.0 * (random.random()*0.05 + 0.95)) * (1)
            # 均匀分布在圆周
            cx = radius * (float(__import__('math').cos(angle)))
            cy = radius * (float(__import__('math').sin(angle)))
            centers.append((cx, cy))

        # 将行星平均分配到各簇
        cluster_planets: List[List[str]] = [[] for _ in range(num_clusters)]
        planet_names = self._generate_planet_names()
        all_ids: List[str] = []
        for i in range(self.num_planets):
            pid = f"planet_{i}"
            all_ids.append(pid)
            cluster_idx = i % max(1, num_clusters)
            cluster_planets[cluster_idx].append(pid)
            self.cluster_labels[pid] = cluster_idx

        # 生成星球与位置
        for i, pid in enumerate(all_ids):
            cidx = self.cluster_labels[pid]
            cx, cy = centers[cidx]
            # 高斯散布
            x = cx + random.gauss(0, 120)
            y = cy + random.gauss(0, 120)
            planet_type = random.choice(list(PlanetType))
            planet = Planet(
                id=pid,
                name=planet_names[i],
                type=planet_type,
                position=(int(x), int(y))
            )
            game_state.planets[pid] = planet

        # 构建边：簇内 k 近邻连接
        def dist2(a: Tuple[int, int], b: Tuple[int, int]) -> float:
            dx = a[0] - b[0]
            dy = a[1] - b[1]
            return dx*dx + dy*dy

        k_intra = max(3, self.num_planets // max(10, num_clusters*5))
        for cidx in range(num_clusters):
            ids = cluster_planets[cidx]
            for i, pid in enumerate(ids):
                pos_i = game_state.planets[pid].position
                # 找到同簇内最近的 k 个
                neighbors = sorted(
                    [other for other in ids if other != pid],
                    key=lambda oid: dist2(pos_i, game_state.planets[oid].position)
                )[:k_intra]
                for nid in neighbors:
                    edge = (pid, nid)
                    if edge not in game_state.connections and (nid, pid) not in game_state.connections:
                        game_state.connections.append(edge)

        # 跨簇桥接：相邻簇各取若干节点连接
        bridges_per_pair = 2 if num_clusters > 1 else 0
        for cidx in range(num_clusters):
            next_idx = (cidx + 1) % num_clusters
            if next_idx == cidx:
                continue
            a_ids = cluster_planets[cidx]
            b_ids = cluster_planets[next_idx]
            # 选择靠近中心的前若干
            def by_center(pid: str, center: Tuple[float,float]):
                return dist2(game_state.planets[pid].position, (center[0], center[1]))
            a_sorted = sorted(a_ids, key=lambda pid: by_center(pid, centers[cidx]))
            b_sorted = sorted(b_ids, key=lambda pid: by_center(pid, centers[next_idx]))
            for bi in range(bridges_per_pair):
                if bi < len(a_sorted) and bi < len(b_sorted):
                    pa = a_sorted[bi]
                    pb = b_sorted[bi]
                    edge = (pa, pb)
                    if edge not in game_state.connections and (pb, pa) not in game_state.connections:
                        game_state.connections.append(edge)

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
