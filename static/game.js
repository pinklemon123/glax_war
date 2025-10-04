// Game client JavaScript
const PLANET_TYPE_MAP = {
    desert: "沙漠星",
    oceanic: "海洋星",
    tropical: "热带星",
    arctic: "极寒星",
    barren: "贫瘠星",
    gas_giant: "气态巨星"
};

const BUILDING_NAME_MAP = {
    energy_plant: "能量工厂",
    mining_station: "采矿站",
    research_lab: "研究实验室",
    shipyard: "船坞",
    defense_station: "防御站"
};

const STRATEGY_MODE_LABELS = {
    peace: "维持和平",
    defend: "重点防御",
    attack: "战争计划"
};

const FACTION_COLOR_PALETTE = [
    "#00d4ff",
    "#ff7a45",
    "#9b59b6",
    "#1abc9c",
    "#f1c40f",
    "#e74c3c",
    "#3498db",
    "#27ae60"
];

class GalaxyGame {
    constructor() {
        this.canvas = document.getElementById('galaxy-canvas');
        this.ctx = this.canvas.getContext('2d');
        this.gameState = null;
        this.selectedPlanet = null;
        this.camera = { x: 0, y: 0, zoom: 1 };
        this.isDragging = false;
        this.lastMousePos = { x: 0, y: 0 };
        this.connectionPhase = 0;
        this.adjacencyMap = {};
        this.connectionCache = {};
        this.factionColors = {};
        this.draggingNode = null;
        this.truceTimer = null;
    // 可视化舰队移动选择
    this.selectedFleetId = null;
    this.highlightNeighbors = new Set();
    this._bannerEl = null;
    // 自定义背景图（可选）
    this.bgImage = null;
    // 拖拽舰队移动/巡逻状态
    this._dragState = { active: false, fleetId: null, start: { x: 0, y: 0 }, cur: { x: 0, y: 0 } };

        this.initCanvas();
        this.initEventListeners();
        this.startAnimation();
    }

    initCanvas() {
        this.resizeCanvas();
        window.addEventListener('resize', () => this.resizeCanvas());
    }
    
    resizeCanvas() {
        const container = document.getElementById('canvas-container');
        this.canvas.width = container.clientWidth;
        this.canvas.height = container.clientHeight;
        this.camera.x = this.canvas.width / 2;
        this.camera.y = this.canvas.height / 2;
        this.render();
    }
    
    initEventListeners() {
        // New game button
        document.getElementById('new-game-btn').addEventListener('click', () => {
            this.newGame();
        });
        
        // End turn button
        document.getElementById('end-turn-btn').addEventListener('click', () => {
            this.endTurn();
        });

        // Auto end-turn toggle
        const autoChk = document.getElementById('auto-end-turn');
        if (autoChk) {
            autoChk.addEventListener('change', () => {
                if (autoChk.checked) {
                    this._autoLoopTurns();
                }
            });
        }

        // 切换战后继续
        const postgameBtn = document.getElementById('toggle-postgame-btn');
        if (postgameBtn) {
            postgameBtn.addEventListener('click', async () => {
                try {
                    const resp = await fetch('/api/game/continue', { method: 'POST' });
                    const data = await resp.json();
                    if (data.success) {
                        this.gameState = data.game_state || this.gameState;
                        this.updateUI();
                        alert(`战后继续：${this.gameState.allow_postgame ? '已开启' : '已关闭'}`);
                    } else {
                        alert('操作失败：' + (data.message || '未知错误'));
                    }
                } catch (e) {
                    alert('网络错误：' + e.message);
                }
            });
        }

        // 导出编年史
        const expBtn = document.getElementById('export-chronicle-btn');
        if (expBtn) {
            expBtn.addEventListener('click', async () => {
                try {
                    const resp = await fetch('/api/game/chronicle');
                    const data = await resp.json();
                    if (!data.success) { alert('导出失败：' + (data.message || '未知错误')); return; }
                    const blob = new Blob([data.markdown || ''], { type: 'text/markdown;charset=utf-8' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    const turn = this.gameState ? this.gameState.turn : 0;
                    a.href = url;
                    a.download = `glax_chronicle_turn_${turn}.md`;
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 0);
                } catch (e) {
                    alert('导出失败：' + e.message);
                }
            });
        }

        // 切换AI接管玩家
        const aiBtn = document.getElementById('toggle-ai-btn');
        if (aiBtn) {
            aiBtn.addEventListener('click', async () => {
                try {
                    const resp = await fetch('/api/game/ai_takeover', { method: 'POST' });
                    const data = await resp.json();
                    if (data.success) {
                        this.gameState = data.game_state || this.gameState;
                        this.updateUI();
                        alert(`AI接管玩家：${this.gameState.ai_takeover_player ? '已启用' : '已关闭'}`);
                    } else {
                        alert('操作失败：' + (data.message || '未知错误'));
                    }
                } catch (e) {
                    alert('网络错误：' + e.message);
                }
            });
        }

        // 规则说明
        const rulesBtn = document.getElementById('show-rules-btn');
        if (rulesBtn && !rulesBtn._bound) {
            rulesBtn._bound = true;
            rulesBtn.addEventListener('click', async () => {
                try {
                    const resp = await fetch('/api/game/rules');
                    const data = await resp.json();
                    if (!data.success) { alert('加载规则失败'); return; }
                    const modal = document.getElementById('rules-modal');
                    const body = document.getElementById('rules-modal-body');
                    const closeBtn = document.getElementById('rules-modal-close');
                    if (body) {
                        const r = data.rules || {};
                        const sec = (title, arr) => `<h3 style="margin-top:8px; color:#88ccff;">${title}</h3><ul style="margin-left:16px;">${(arr||[]).map(s=>`<li style=\"margin:4px 0;\">${s}</li>`).join('')}</ul>`;
                        body.innerHTML = sec('核心', r.core) + sec('战斗/强袭', r.combat) + sec('背城一击与特权', r.assault) + sec('分派与巡逻', r.alloc) + sec('可选AI(LLM)', r.llm);
                    }
                    if (modal) modal.style.display = 'block';
                    if (closeBtn && !closeBtn._bound) { closeBtn._bound = true; closeBtn.onclick = () => modal.style.display = 'none'; }
                    if (modal) modal.onclick = (ev) => { if (ev.target === modal) modal.style.display = 'none'; };
                } catch (e) {
                    alert('加载规则失败：' + e.message);
                }
            });
        }

        // 战后叙事
        const nbtn = document.getElementById('show-narrative-btn');
        if (nbtn && !nbtn._bound) {
            nbtn._bound = true;
            nbtn.addEventListener('click', async () => {
                try {
                    const resp = await fetch('/api/game/narrative');
                    const data = await resp.json();
                    if (!data.success) { alert('加载失败'); return; }
                    const modal = document.getElementById('narrative-modal');
                    const body = document.getElementById('narrative-modal-body');
                    const closeBtn = document.getElementById('narrative-modal-close');
                    if (body) body.textContent = data.narrative || '';
                    if (modal) modal.style.display = 'block';
                    if (closeBtn && !closeBtn._bound) { closeBtn._bound = true; closeBtn.onclick = () => modal.style.display = 'none'; }
                    if (modal) modal.onclick = (ev) => { if (ev.target === modal) modal.style.display = 'none'; };
                } catch (e) {
                    alert('加载失败：' + e.message);
                }
            });
        }

        // 选择背景图
        const bgInput = document.getElementById('bg-file');
        if (bgInput) {
            bgInput.addEventListener('change', (ev) => {
                const file = ev.target.files && ev.target.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = () => {
                    const img = new Image();
                    img.onload = () => { this.bgImage = img; this.render(); };
                    img.src = reader.result;
                };
                reader.readAsDataURL(file);
            });
        }
        
        // Canvas interaction
        this.canvas.addEventListener('mousedown', (e) => this.onMouseDown(e));
    this.canvas.addEventListener('mousemove', (e) => { this._showPlanetTooltip(e); this.onMouseMove(e); });
    this.canvas.addEventListener('mouseup', (e) => this.onMouseUp(e));
        this.canvas.addEventListener('wheel', (e) => this.onWheel(e));
        this.canvas.addEventListener('click', (e) => this.onClick(e));
        
        // Command panel
        document.getElementById('command-type').addEventListener('change', (e) => {
            this.updateCommandParams(e.target.value);
        });
        
        document.getElementById('submit-command-btn').addEventListener('click', () => {
            this.submitCommand();
        });

        // 键盘快捷键：ESC 取消移动模式
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.setSelectedFleet(null);
            }
        });
    }

    startAnimation() {
        const animate = () => {
            this.connectionPhase = (this.connectionPhase + 0.8) % 200;
            if (this.gameState) {
                this.render();
            }
            this.animationHandle = requestAnimationFrame(animate);
        };
        this.animationHandle = requestAnimationFrame(animate);
    }

    buildAdjacencyMap() {
        this.adjacencyMap = {};
        if (!this.gameState || !this.gameState.connections) return;
        for (const conn of this.gameState.connections) {
            const [a, b] = conn;
            if (!this.adjacencyMap[a]) this.adjacencyMap[a] = new Set();
            if (!this.adjacencyMap[b]) this.adjacencyMap[b] = new Set();
            this.adjacencyMap[a].add(b);
            this.adjacencyMap[b].add(a);
        }
    }

    updateFactionColors() {
        this.factionColors = {};
        if (!this.gameState || !this.gameState.factions) return;

        const factionIds = Object.keys(this.gameState.factions);
        let paletteIndex = 0;
        factionIds.forEach((id) => {
            if (id === 'player') {
                this.factionColors[id] = '#00ff88';
                return;
            }
            const color = FACTION_COLOR_PALETTE[paletteIndex % FACTION_COLOR_PALETTE.length];
            this.factionColors[id] = color;
            paletteIndex += 1;
        });
        if (!this.factionColors.player) {
            this.factionColors.player = '#00ff88';
        }
    }

    getFactionColor(factionId) {
        if (!factionId) return '#888888';
        if (!this.factionColors[factionId]) {
            this.factionColors[factionId] = FACTION_COLOR_PALETTE[Math.floor(Math.random() * FACTION_COLOR_PALETTE.length)];
        }
        return this.factionColors[factionId];
    }

    toRGBA(hex, alpha = 1) {
        const sanitized = hex.replace('#', '');
        const bigint = parseInt(sanitized, 16);
        const r = (bigint >> 16) & 255;
        const g = (bigint >> 8) & 255;
        const b = bigint & 255;
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    getAdjacentPlanets(planetId) {
        if (!this.adjacencyMap || !this.adjacencyMap[planetId]) return [];
        return Array.from(this.adjacencyMap[planetId]);
    }
    
    async newGame() {
        this.showLoading(true);
        try {
            // 使用综合评价胜利（不启用科技/经济即时胜利）
            const response = await fetch('/api/game/new?planets=30&ai=3&max_turns=120');
            const data = await response.json();
            if (data.success) {
                this.gameState = data.game_state;
                this.buildAdjacencyMap();
                this.updateFactionColors();
                this.updateUI();
                this.refreshPowerStats();
                this.refreshVictoryProgress();
                this.startTruceCountdown();
                this.render();
                document.getElementById('end-turn-btn').disabled = false;
            } else {
                alert('创建游戏失败: ' + data.message);
            }
        } catch (error) {
            alert('错误: ' + error.message);
        } finally {
            this.showLoading(false);
        }
    }
    
    async endTurn() {
        this.showLoading(true);
        try {
            const response = await fetch('/api/game/end_turn', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            if (data.success) {
                this.gameState = data.game_state;
                this.buildAdjacencyMap();
                this.updateFactionColors();
                this.updateUI();
                this.refreshPowerStats();
                this.refreshVictoryProgress();
                this.startTruceCountdown();
                this.render();
                if (this.gameState.game_over && !this.gameState.allow_postgame) {
                    document.getElementById('end-turn-btn').disabled = true;
                    const msg = `游戏结束：${this.gameState.end_reason}，胜者：${this.gameState.winner}`;
                    const go = confirm(msg + "\n\n是否现在生成战后故事并查看？");
                    if (go) { window.location.href = '/story'; }
                }
            } else {
                alert('结束回合失败: ' + data.message);
            }
        } catch (error) {
            alert('错误: ' + error.message);
        } finally {
            this.showLoading(false);
        }
    }
    async refreshPowerStats() {
        try {
            const el = document.getElementById('power-stats');
            if (!el) return;
            const resp = await fetch('/api/game/power_stats');
            const data = await resp.json();
            if (!data.success) { el.textContent = '加载失败'; return; }
            const stats = data.stats || [];
            if (!stats.length) { el.textContent = '暂无数据'; return; }
            const max = Math.max(...stats.map(s => s.total));
            el.innerHTML = stats.map(s => {
                const pct = max > 0 ? Math.round((s.total / max) * 100) : 0;
                const br = s.breakdown || {};
                const ex = s.extras || {};
                const assaultTag = ex.assault_always ? '<span style="margin-left:6px;padding:2px 6px;border-radius:4px;background:rgba(255,100,80,0.15);color:#ff876a;border:1px solid rgba(255,100,80,0.25);font-weight:bold;">强袭特权</span>' : '';
                return `
                    <div style="margin:8px 0; padding-bottom:6px; border-bottom:1px dashed rgba(255,255,255,0.08)">
                        <div style="display:flex; justify-content:space-between; font-size:12px; color:#ccc;">
                            <strong>${s.name} ${assaultTag}</strong>
                            <span>总分 ${s.total.toFixed(1)}（相对 ${pct}%）</span>
                        </div>
                        <div class="bar" style="margin:6px 0 8px 0;"><span style="width:${pct}%;"></span></div>
                        <div style="display:grid; grid-template-columns: repeat(2, 1fr); gap:4px; font-size:12px; color:#aaaacc;">
                            <div>资源: ${br.resources?.toFixed(1) || '0.0'}</div>
                            <div>星球: ${br.planets?.toFixed(1) || '0.0'}</div>
                            <div>人口: ${br.population?.toFixed(1) || '0.0'}</div>
                            <div>防御: ${br.defense?.toFixed(1) || '0.0'}</div>
                            <div>舰队: ${br.fleets?.toFixed(1) || '0.0'}</div>
                            <div>科技: ${br.tech?.toFixed(1) || '0.0'}</div>
                            <div>舰队数: ${ex.fleet_count ?? '-'}</div>
                            <div>舰船总数: ${ex.ship_count_total ?? '-'}</div>
                            <div>科技数: ${ex.tech_count ?? '-'}</div>
                            <div style="grid-column: span 2;">声誉修正: ×${(br.reputation_mod||1).toFixed(2)}</div>
                            <div>围攻(攻)星球: ${ex.siege_attacking_planets ?? 0}</div>
                            <div>围攻(攻)点数: ${ex.siege_attacking_points ?? 0}</div>
                            <div>围攻(守)星球: ${ex.siege_defending_planets ?? 0}</div>
                            <div>围攻(守)点数: ${ex.siege_defending_points ?? 0}</div>
                        </div>
                    </div>
                `;
            }).join('');
        } catch (e) {
            const el = document.getElementById('power-stats');
            if (el) el.textContent = '加载失败';
        }
    }

    startTruceCountdown() {
        const panel = document.getElementById('truce-panel');
        const label = document.getElementById('truce-countdown');
        if (!this.gameState) return;
        const active = this.gameState.truce_active;
        if (!active) {
            panel.style.display = 'none';
            if (this.truceTimer) { clearInterval(this.truceTimer); this.truceTimer = null; }
            return;
        }
        panel.style.display = 'block';
        const until = this.gameState.truce_until || 0;
        const tick = () => {
            const now = Math.floor(Date.now() / 1000);
            const remain = Math.max(0, Math.floor(until - now));
            const mm = String(Math.floor(remain / 60)).padStart(2, '0');
            const ss = String(remain % 60).padStart(2, '0');
            label.textContent = `停战剩余 ${mm}:${ss}`;
            if (remain <= 0) {
                clearInterval(this.truceTimer);
                this.truceTimer = null;
                panel.style.display = 'none';
                alert('停战结束，战斗与占领已开放！');
            }
        };
        if (this.truceTimer) clearInterval(this.truceTimer);
        this.truceTimer = setInterval(tick, 1000);
        tick();
    }
    
    async submitCommand() {
        const commandType = document.getElementById('command-type').value;
        if (!commandType) return;

        const params = this.getCommandParams(commandType);
        if (!params) return;

        try {
            const data = await this.postCommand(commandType, params);
            if (data.success) {
                alert('指令已提交！');
                document.getElementById('command-type').value = '';
                this.updateCommandParams('');
            } else {
                alert('提交失败: ' + data.message);
            }
        } catch (error) {
            alert('错误: ' + error.message);
        }
    }
    
    async refreshVictoryProgress() {
        try {
            const resp = await fetch('/api/game/victory_progress');
            const data = await resp.json();
            if (!data.success) return;
            const panel = document.getElementById('victory-status');
            const truceHint = document.getElementById('truce-hint');
            const allowPostTxt = this.gameState && this.gameState.allow_postgame ? '已开启' : '关闭';
            const aiTakeoverTxt = this.gameState && this.gameState.ai_takeover_player ? '启用' : '关闭';

            // 胜利说明：仅采用综合评价；科技/经济胜利显示为关闭状态
            const techRequired = '';
            const econRecent = '';

            panel.innerHTML = `
                <div><strong>游戏结束:</strong> ${data.game_over ? '是' : '否'}</div>
                <div><strong>胜者:</strong> ${data.winner || '-'}</div>
                <div><strong>原因:</strong> ${data.end_reason || '-'}</div>
                ${data.game_over ? '<div style="margin-top:8px;"><button id="go-story" style="background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;border-radius:6px;padding:6px 10px;cursor:pointer;">生成故事并查看</button></div>' : ''}
                <hr>
                <div><strong>运行状态</strong></div>
                <div>战后继续：${allowPostTxt}</div>
                <div>AI接管玩家：${aiTakeoverTxt}</div>
                <hr>
                <div><strong>胜利规则：</strong>仅按综合评价判定（统治/淘汰或回合上限比综合实力）。</div>
                <div style="color:#aaa;">科技胜：关闭；经济胜：关闭</div>
            `;

            // 绑定跳转按钮
            const goBtn = document.getElementById('go-story');
            if (goBtn && !goBtn._bound) { goBtn._bound = true; goBtn.addEventListener('click', () => { window.location.href = '/story'; }); }

            // 标注停战状态（仅展示，实际判定由后端控制）
            if (this.gameState && this.gameState.truce_active) {
                truceHint.textContent = '停战保护中：胜利条件不会在停战期间结算';
            } else {
                truceHint.textContent = '停战已解除：胜利条件将正常结算';
            }
        } catch (e) {
            console.warn('victory_progress fetch failed', e);
        }
    }

    async postCommand(commandType, parameters, factionId = 'player') {
        try {
            const response = await fetch('/api/game/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    faction_id: factionId,
                    command_type: commandType,
                    parameters
                })
            });
            return await response.json();
        } catch (error) {
            throw error;
        }
    }

    getCommandParams(commandType) {
        const params = {};

        if (commandType === 'colonize') {
            const option = document.getElementById('param-colonize-target');
            if (!option || !option.value) {
                alert('请选择殖民目标');
                return null;
            }
            const [from, to] = option.value.split('|');
            params.from_planet = from;
            params.to_planet = to;
        } else if (commandType === 'build') {
            const planet = document.getElementById('param-planet').value;
            const building = document.getElementById('param-building').value;
            if (!planet || !building) {
                alert('请填写所有参数');
                return null;
            }
            params.planet = planet;
            params.building = building;
        } else if (commandType === 'research') {
            const tech = document.getElementById('param-tech').value;
            if (!tech) {
                alert('请选择科技');
                return null;
            }
            params.technology = tech;
        } else if (commandType === 'strategy') {
            const modeSelect = document.getElementById('param-strategy-mode');
            if (!modeSelect) return null;
            const mode = modeSelect.value;
            if (!mode) {
                alert('请选择战略模式');
                return null;
            }
            params.mode = mode;
            if (mode === 'attack') {
                const targetSelect = document.getElementById('param-strategy-target');
                if (!targetSelect || !targetSelect.value) {
                    alert('请选择进攻目标势力');
                    return null;
                }
                params.target = targetSelect.value;
            } else if (mode === 'defend') {
                const checkboxes = document.querySelectorAll('.strategy-planet-checkbox:checked');
                const selected = Array.from(checkboxes).map(cb => cb.value);
                if (!selected.length) {
                    alert('请至少选择一个重点防御星球');
                    return null;
                }
                params.planets = selected;
            }
        }

        return params;
    }

    getColonizationCandidates() {
        const results = {};
        if (!this.gameState || !this.gameState.factions) return [];
        const playerFaction = this.gameState.factions['player'];
        if (!playerFaction) return [];

        for (const fromId of playerFaction.planets) {
            const neighbors = this.getAdjacentPlanets(fromId);
            const fromPlanet = this.gameState.planets[fromId];
            for (const targetId of neighbors) {
                const targetPlanet = this.gameState.planets[targetId];
                if (!targetPlanet || targetPlanet.owner) continue;
                const existing = results[targetId];
                const population = fromPlanet ? fromPlanet.population : 0;
                if (!existing || population > existing.fromPopulation) {
                    results[targetId] = {
                        targetId,
                        targetName: targetPlanet.name,
                        fromId,
                        fromName: fromPlanet ? fromPlanet.name : fromId,
                        fromPopulation: population
                    };
                }
            }
        }

        return Object.values(results).sort((a, b) => b.fromPopulation - a.fromPopulation);
    }

    renderStrategyDetails(mode) {
        const container = document.getElementById('strategy-details');
        if (!container) return;
        const playerFaction = this.gameState.factions['player'];

        if (mode === 'attack') {
            const targets = Object.values(this.gameState.factions)
                .filter(f => f.id !== 'player')
                .map(f => `<option value="${f.id}">${f.name}</option>`)
                .join('');
            if (!targets) {
                container.innerHTML = '<p>暂无可进攻的势力。</p>';
                return;
            }
            container.innerHTML = `
                <label>进攻目标势力:</label>
                <select id="param-strategy-target">
                    ${targets}
                </select>
                <small>提示：进攻需要与目标星球连通。</small>
            `;
        } else if (mode === 'defend') {
            container.innerHTML = '<p>已进入全局防御模式：本回合内，任意被攻打的己方星球都有机会被自动拦截（消耗防御次数）。</p>';
        } else {
            container.innerHTML = '<p>保持和平，集中发展经济与科技。</p>';
        }
    }

    updateCommandParams(commandType) {
        const container = document.getElementById('command-params');
        container.innerHTML = '';
        
        if (!commandType || !this.gameState) {
            document.getElementById('submit-command-btn').disabled = true;
            return;
        }
        
        const playerFaction = this.gameState.factions['player'];
        if (!playerFaction) return;

        if (commandType === 'colonize') {
            const options = this.getColonizationCandidates();
            if (!options.length) {
                container.innerHTML = '<p>暂无可殖民的空白星球，请探索附近区域。</p>';
                document.getElementById('submit-command-btn').disabled = true;
                return;
            }

            container.innerHTML = `
                <label>殖民目标:</label>
                <select id="param-colonize-target">
                    ${options.map(opt => `<option value="${opt.fromId}|${opt.targetId}">${opt.targetName}（由 ${opt.fromName} 出发）</option>`).join('')}
                </select>
                <small>提示：系统会自动选择综合实力更强的势力完成殖民。</small>
            `;
        } else if (commandType === 'build') {
            container.innerHTML = `
                <label>星球:</label>
                <select id="param-planet">
                    ${playerFaction.planets.map(p => `<option value="${p}">${this.gameState.planets[p].name}</option>`).join('')}
                </select>
                <label>建筑类型:</label>
                <select id="param-building">
                    ${Object.entries(BUILDING_NAME_MAP).map(([value, label]) => `<option value="${value}">${label}</option>`).join('')}
                </select>
            `;
        } else if (commandType === 'research') {
            const availableTechs = Object.keys(this.gameState.technologies).filter(
                t => !playerFaction.technologies.includes(t)
            );
            if (!availableTechs.length) {
                container.innerHTML = '<p>暂无可研究的科技。</p>';
                document.getElementById('submit-command-btn').disabled = true;
                return;
            }
            container.innerHTML = `
                <label>科技:</label>
                <select id="param-tech">
                    ${availableTechs.map(t => {
                        const tech = this.gameState.technologies[t];
                        const label = tech ? tech.name : t;
                        return `<option value="${t}">${label}</option>`;
                    }).join('')}
                </select>
            `;
        } else if (commandType === 'strategy') {
            container.innerHTML = `
                <label>战略模式:</label>
                <select id="param-strategy-mode">
                    <option value="peace">${STRATEGY_MODE_LABELS.peace}</option>
                    <option value="defend">${STRATEGY_MODE_LABELS.defend}</option>
                    <option value="attack">${STRATEGY_MODE_LABELS.attack}</option>
                </select>
                <div id="strategy-details" class="strategy-details"></div>
            `;
            const modeSelect = document.getElementById('param-strategy-mode');
            this.renderStrategyDetails(modeSelect.value);
            modeSelect.addEventListener('change', (event) => {
                this.renderStrategyDetails(event.target.value);
            });
        }

        document.getElementById('submit-command-btn').disabled = false;
    }
    
    updateUI() {
        if (!this.gameState) return;
        
        // Update turn number
        document.getElementById('turn-number').textContent = this.gameState.turn;
        
        // Update resources
        const playerFaction = this.gameState.factions['player'];
        if (playerFaction) {
            document.getElementById('resource-energy').textContent = Math.floor(playerFaction.resources.energy);
            document.getElementById('resource-minerals').textContent = Math.floor(playerFaction.resources.minerals);
            document.getElementById('resource-research').textContent = Math.floor(playerFaction.resources.research);
            
            // Update planet list
            const planetList = document.getElementById('my-planets');
            planetList.innerHTML = playerFaction.planets.map(planetId => {
                const planet = this.gameState.planets[planetId];
                return `
                    <div class="planet-item" onclick="game.selectPlanet('${planetId}')">
                        <strong>${planet.name}</strong><br>
                        <small>人口: ${planet.population}</small>
                    </div>
                `;
            }).join('');
        }
        // 更新战后继续/AI接管按钮文案与回合按钮可用状态
        const postgameBtn = document.getElementById('toggle-postgame-btn');
        if (postgameBtn) postgameBtn.textContent = this.gameState.allow_postgame ? '关闭战后继续' : '开启战后继续';
        const aiBtn = document.getElementById('toggle-ai-btn');
        if (aiBtn) aiBtn.textContent = this.gameState.ai_takeover_player ? '取消AI接管' : 'AI接管玩家';
        const endTurnBtn = document.getElementById('end-turn-btn');
        if (endTurnBtn) endTurnBtn.disabled = !!(this.gameState.game_over && !this.gameState.allow_postgame);
        
        // Update events
        if (this.gameState.events) {
            const eventLog = document.getElementById('event-log');
            eventLog.innerHTML = this.gameState.events.slice(-10).reverse().map(event => `
                <div class="event-item">
                    <div class="event-time">回合 ${event.turn}</div>
                    <div>${event.description}</div>
                </div>
            `).join('');
        }

        // 刷新舰队列表（只显示玩家）
        this.refreshFleetPanel();

        const currentCommand = document.getElementById('command-type');
        if (currentCommand && currentCommand.value) {
            this.updateCommandParams(currentCommand.value);
        }
    }

    async refreshFleetPanel() {
        const panel = document.getElementById('fleet-list');
        if (!panel) return;
        try {
            const resp = await fetch('/api/fleets?owner=player');
            const data = await resp.json();
            if (!data.success) { panel.textContent = '加载失败'; return; }
            const fleets = data.fleets || [];
            if (!fleets.length) { panel.textContent = '暂无舰队'; return; }
            panel.innerHTML = fleets.map(f => {
                const p = this.gameState.planets[f.position];
                const name = p ? p.name : f.position;
                const total = Object.values(f.ships || {}).reduce((a,b)=>a+b,0);
                return `<div class="fleet-row" data-fid="${f.id}" style="margin:6px 0; font-size:12px; cursor:pointer;">#${f.id} @ ${name} | 舰数:${total}</div>`;
            }).join('');

            // 填充选择器
            const sel = document.getElementById('fleet-select');
            if (sel) {
                sel.innerHTML = fleets.map(f => {
                    const p = this.gameState.planets[f.position];
                    const name = p ? p.name : f.position;
                    return `<option value="${f.id}" data-pos="${f.position}">${f.id} @ ${name}</option>`;
                }).join('');
            }
            const destSel = document.getElementById('fleet-dest');
            const computeAndFillDests = () => {
                if (!destSel) return;
                let basePlanetId = null;
                if (sel && sel.value) {
                    const cur = fleets.find(ff => ff.id === sel.value);
                    basePlanetId = cur ? cur.position : null;
                }
                if (!basePlanetId && this.selectedPlanet) basePlanetId = this.selectedPlanet;
                const neighbors = basePlanetId ? (this.connectionCache[basePlanetId] || this.getAdjacentPlanets(basePlanetId)) : [];
                destSel.innerHTML = neighbors.map(pid => `<option value="${pid}">${this.gameState.planets[pid] ? this.gameState.planets[pid].name : pid}</option>`).join('');
            };
            computeAndFillDests();

            if (sel && !sel._boundChange) {
                sel._boundChange = true;
                sel.addEventListener('change', () => computeAndFillDests());
            }
        } catch (e) {
            panel.textContent = '加载失败';
        }

        // 绑定按钮
        const createBtn = document.getElementById('create-fleet-btn');
        if (createBtn && !createBtn._bound) {
            createBtn._bound = true;
            createBtn.addEventListener('click', async () => {
                if (!this.selectedPlanet) { alert('请先在地图上选中一个己方星球'); return; }
                const planet = this.gameState.planets[this.selectedPlanet];
                if (!planet || planet.owner !== 'player') { alert('只能在己方星球创建'); return; }
                // 以一个小编制为例
                const body = { owner: 'player', planet_id: this.selectedPlanet, ships: { corvette: 2, scout: 2 } };
                const resp = await fetch('/api/fleet/create', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
                const d = await resp.json();
                if (d.success) { alert('已创建舰队'); this.updateUI(); }
                else { alert('创建失败：' + d.message); }
            });
        }

        const moveBtn = document.getElementById('move-fleet-btn');
        if (moveBtn && !moveBtn._bound) {
            moveBtn._bound = true;
            moveBtn.addEventListener('click', async () => {
                const sel = document.getElementById('fleet-select');
                const destSel = document.getElementById('fleet-dest');
                if (!sel || !sel.value) { alert('请选择舰队'); return; }
                if (!destSel || !destSel.value) { alert('请选择目的地'); return; }
                const resp = await fetch('/api/fleet/move', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ owner:'player', fleet_id: sel.value, destination: destSel.value })});
                const d = await resp.json();
                if (d.success) { alert('已下达移动命令'); this.updateUI(); }
                else { alert('移动失败：' + d.message); }
            });
        }

        // 让每一条舰队条目可点击：进入可视化目的地选择并弹出详情模态
        const rows = panel.querySelectorAll('.fleet-row');
        rows.forEach(row => {
            if (row._bound) return; row._bound = true;
            row.addEventListener('click', () => {
                const fid = row.getAttribute('data-fid');
                this.setSelectedFleet(fid);
                this.openFleetModal(fid);
            });
        });

        const reinforceBtn = document.getElementById('reinforce-btn');
        if (reinforceBtn && !reinforceBtn._bound) {
            reinforceBtn._bound = true;
            reinforceBtn.addEventListener('click', async () => {
                const sel = document.getElementById('fleet-select');
                if (!sel || !sel.value) { alert('请选择舰队'); return; }
                const delta = {
                    corvette: parseInt(document.getElementById('reinforce-corvette').value || '0', 10),
                    scout: parseInt(document.getElementById('reinforce-scout').value || '0', 10),
                    destroyer: parseInt(document.getElementById('reinforce-destroyer').value || '0', 10),
                    cruiser: parseInt(document.getElementById('reinforce-cruiser').value || '0', 10),
                    battleship: parseInt(document.getElementById('reinforce-battleship').value || '0', 10)
                };
                const resp = await fetch('/api/fleet/reinforce', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ owner:'player', fleet_id: sel.value, delta })});
                const d = await resp.json();
                if (d.success) { alert('已应用'); this.updateUI(); }
                else { alert('失败：' + d.message); }
            });
        }
    }

    openFleetModal(fid) {
        const modal = document.getElementById('fleet-modal');
        const body = document.getElementById('fleet-modal-body');
        const closeBtn = document.getElementById('fleet-modal-close');
        const fleet = this.gameState && this.gameState.fleets ? this.gameState.fleets[fid] : null;
        if (!modal || !body || !fleet) return;
    const ships = fleet.ships || {};
    const neighbors = fleet.position ? (this.connectionCache[fleet.position] || this.getAdjacentPlanets(fleet.position)) : [];
        const val = (n) => (typeof n === 'number' ? n : 0);
        body.innerHTML = `
            <h2>舰队详情：${fid}</h2>
            <p><strong>所在星球：</strong>${this.gameState.planets[fleet.position] ? this.gameState.planets[fleet.position].name : fleet.position}</p>
            <ul>
                <li>侦察：${val(ships.scout)}</li>
                <li>护卫：${val(ships.corvette)}</li>
                <li>驱逐：${val(ships.destroyer)}</li>
                <li>巡洋：${val(ships.cruiser)}</li>
                <li>战列：${val(ships.battleship)}</li>
            </ul>
            <div class="template-buttons">
                <h3>编队模板</h3>
                <button data-tmpl="scout">侦察队(侦察6)</button>
                <button data-tmpl="strike">突击队(护卫6, 驱逐2)</button>
                <button data-tmpl="garrison">守备队(护卫4, 巡洋1)</button>
            </div>
            <div style="margin-top:10px;">
                <h3>巡逻</h3>
                <div>
                    <label>选择一条相邻连线：</label>
                    <select id="patrol-edge-select">
                        ${neighbors.map(pid => {
                            const p = this.gameState.planets[pid];
                            const name = p ? p.name : pid;
                            return `<option value="${fleet.position}|${pid}">${this.gameState.planets[fleet.position]?.name || fleet.position} - ${name}</option>`;
                        }).join('')}
                    </select>
                    <button id="patrol-apply">设置巡逻</button>
                    <button id="patrol-cancel">取消巡逻</button>
                </div>
                <small>巡逻会对跨越该连线的敌军产生拦截概率：Σ(巡逻舰队战力)×0.02，最多100%。</small>
            </div>
        `;
        modal.style.display = 'block';
        if (closeBtn && !closeBtn._bound) {
            closeBtn._bound = true;
            closeBtn.onclick = () => { modal.style.display = 'none'; };
        }
        modal.onclick = (ev) => { if (ev.target === modal) modal.style.display = 'none'; };

        const applyTemplate = async (tmpl) => {
            const defs = {
                scout: { scout: 6 },
                strike: { corvette: 6, destroyer: 2 },
                garrison: { corvette: 4, cruiser: 1 }
            };
            const target = defs[tmpl];
            if (!target) return;
            const cur = {
                scout: val(ships.scout),
                corvette: val(ships.corvette),
                destroyer: val(ships.destroyer),
                cruiser: val(ships.cruiser),
                battleship: val(ships.battleship)
            };
            const delta = {};
            Object.keys(target).forEach(k => { delta[k] = (target[k] || 0) - (cur[k] || 0); });
            const resp = await fetch('/api/fleet/reinforce', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ owner:'player', fleet_id: fid, delta })});
            const d = await resp.json();
            if (d.success) { alert('模板已套用'); modal.style.display = 'none'; this.updateUI(); }
            else { alert('套用失败：' + d.message); }
        };

        body.querySelectorAll('.template-buttons button').forEach(btn => {
            btn.addEventListener('click', async () => {
                const tmpl = btn.getAttribute('data-tmpl');
                await applyTemplate(tmpl);
            });
        });

        const applyPatrol = async () => {
            const sel = document.getElementById('patrol-edge-select');
            if (!sel || !sel.value) return;
            const [a,b] = sel.value.split('|');
            const resp = await fetch('/api/fleet/patrol', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ owner:'player', fleet_id: fid, a, b })});
            const d = await resp.json();
            if (d.success) { alert('已设置巡逻'); modal.style.display = 'none'; this.updateUI(); }
            else { alert('设置失败：' + d.message); }
        };
        const cancelPatrol = async () => {
            const resp = await fetch('/api/fleet/patrol', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ owner:'player', fleet_id: fid })});
            const d = await resp.json();
            if (d.success) { alert('已取消巡逻'); modal.style.display = 'none'; this.updateUI(); }
            else { alert('取消失败：' + d.message); }
        };
        const btnApply = document.getElementById('patrol-apply');
        const btnCancel = document.getElementById('patrol-cancel');
        if (btnApply) btnApply.addEventListener('click', applyPatrol);
        if (btnCancel) btnCancel.addEventListener('click', cancelPatrol);
    }
    
    selectPlanet(planetId) {
        this.selectedPlanet = planetId;
        this.updatePlanetDetails(planetId);
        this.render();
        this.prefillColonizeSelection(planetId);
        // 刷新舰队面板目的地列表依赖选中星球
        this.refreshFleetPanel();
    }

    async updatePlanetDetails(planetId) {
        try {
            const response = await fetch(`/api/game/planet/${planetId}`);
            const data = await response.json();
            if (data.success) {
                const planet = data.planet;
                // 拉取强袭预览，用于决策提示
                let preview = null;
                try {
                    const respPrev = await fetch(`/api/planet/assault_preview?planet_id=${planetId}&faction_id=player`);
                    const dprev = await respPrev.json();
                    if (dprev && dprev.success) preview = dprev;
                } catch (_) {}
                this.connectionCache[planetId] = data.connected_planets || [];
                const detailsDiv = document.getElementById('planet-details');
                const planetType = PLANET_TYPE_MAP[planet.type] || planet.type;
                const ownerFaction = planet.owner ? this.gameState.factions[planet.owner] : null;
                const ownerName = ownerFaction ? ownerFaction.name : '无';
                const buildingList = planet.buildings.length
                    ? planet.buildings.map(b => `<li>${BUILDING_NAME_MAP[b] || b}</li>`).join('')
                    : '<li>无</li>';
                const connectedList = (data.connected_planets || []).map(p => {
                    const connPlanet = this.gameState.planets[p];
                    const connName = connPlanet ? connPlanet.name : p;
                    return `<li onclick="game.selectPlanet('${p}')" style="cursor:pointer; color: #00d4ff;">${connName}</li>`;
                }).join('') || '<li>无</li>';

                const colonizeOptions = this.getColonizationCandidates();
                const directOption = colonizeOptions.find(opt => opt.targetId === planetId);
                const canColonize = !planet.owner && directOption;
                const colonizeButton = canColonize
                    ? `<button id="colonize-now-btn" data-from="${directOption.fromId}" data-target="${planetId}">立即殖民该星球</button>`
                    : '';

                const canRename = planet.owner === 'player';
                const renameControls = canRename ? `
                    <div id="rename-controls" style="margin-top:8px;">
                        <input id="rename-input" type="text" maxlength="24" placeholder="新名称，≤24字符" style="width:100%; padding:6px;" />
                        <button id="rename-btn" style="margin-top:6px;">重命名该星球</button>
                        <small style="color:#aaaacc;">允许中文/英文/数字/空格/下划线/连字符</small>
                    </div>
                ` : '';

                const myFaction = this.gameState.factions['player'];
                const myCap = (myFaction.planet_alloc_caps||{})[planetId] ?? '';
                const neighborsForAlloc = (data.connected_planets||[]);
                const myShipsHere = data.player_ship_count || 0;
                const desperateThreshold = data.desperate_threshold || (this.gameState.rules ? this.gameState.rules.desperate_capture_threshold : 10) || 10;
                const playerHasNoPlanets = !this.gameState.factions['player'] || (this.gameState.factions['player'].planets||[]).length === 0;
                const assaultAlways = !!data.assault_always_player;
                const canAssault = ((playerHasNoPlanets || assaultAlways) && myShipsHere > desperateThreshold && planet.owner && planet.owner !== 'player');
                // 预览信息渲染
                let assaultInfoHtml = '';
                if (preview) {
                    const p = preview.capture || null;
                    const prob = p ? (p.prob * 100).toFixed(1) + '%' : '-';
                    const atk = p && p.factors && p.factors.atk ? p.factors.atk : {};
                    const def = p && p.factors && p.factors.def ? p.factors.def : {};
                    assaultInfoHtml = `
                        <div style="margin-top:6px; padding:8px; background:rgba(0,0,0,0.25); border-left:3px solid #ffb199;">
                            <div style="color:#ffb199; font-weight:bold;">强袭预览</div>
                            <div>资格：${preview.qualified ? '具备' : '不具备'}（特权：${preview.assault_always ? '有' : '无'}）</div>
                            <div>己方舰数：${preview.ships_here} / 阈值：>${preview.threshold}</div>
                            <div>成功率（估算）：<strong>${prob}</strong></div>
                            ${p ? `<div style="margin-top:6px; display:grid; grid-template-columns: 1fr 1fr; gap:6px; font-size:12px; color:#ccc;">
                                <div>
                                    <div style="color:#aaffcc;">进攻因子</div>
                                    <div>原始战力：${(p.factors?.atk?.raw||0).toFixed?.(1) ?? p.factors?.atk?.raw ?? '-'}</div>
                                    <div>熟练修正：×${(p.factors?.atk?.prof_mult||1).toFixed?.(2) ?? p.factors?.atk?.prof_mult ?? '1.00'}</div>
                                    <div>科技修正：×${(p.factors?.atk?.tech_mult||1).toFixed?.(2) ?? p.factors?.atk?.tech_mult ?? '1.00'}</div>
                                    <div>邻接支援：×${(p.factors?.atk?.adj_mult||1).toFixed?.(2) ?? p.factors?.atk?.adj_mult ?? '1.00'}</div>
                                </div>
                                <div>
                                    <div style="color:#ffddaa;">防御因子</div>
                                    <div>原始战力：${(p.factors?.def?.raw||0).toFixed?.(1) ?? p.factors?.def?.raw ?? '-'}</div>
                                    <div>建筑/科技：×${(p.factors?.def?.def_mult||1).toFixed?.(2) ?? p.factors?.def?.def_mult ?? '1.00'}</div>
                                    <div>围攻衰减：×${(p.factors?.def?.siege_mult||1).toFixed?.(2) ?? p.factors?.def?.siege_mult ?? '1.00'}</div>
                                    <div>滩头保护：×${(p.factors?.def?.beachhead_mult||1).toFixed?.(2) ?? p.factors?.def?.beachhead_mult ?? '1.00'}</div>
                                </div>
                            </div>` : ''}
                        </div>
                    `;
                }
                const edgeRows = neighborsForAlloc.map(nid => {
                    const key = [planetId, nid].sort().join('|');
                    const cap = (myFaction.edge_alloc_caps||{})[key] ?? '';
                    const name = this.gameState.planets[nid] ? this.gameState.planets[nid].name : nid;
                    return `<div style="display:flex;align-items:center;gap:6px;margin:4px 0;">
                        <span style="min-width:120px;">${(this.gameState.planets[planetId]?.name)||planetId} - ${name}</span>
                        <input class="edge-cap-input" data-a="${planetId}" data-b="${nid}" type="number" min="0" placeholder="巡逻上限" value="${cap}" style="width:90px;" />
                        <button class="edge-cap-save" data-a="${planetId}" data-b="${nid}" style="width:auto;padding:6px 10px;">保存</button>
                    </div>`;
                }).join('');

                detailsDiv.innerHTML = `
                    <h3>${planet.name}</h3>
                    <p><strong>类型:</strong> ${planetType}</p>
                    <p><strong>所有者:</strong> ${ownerName}</p>
                    <p><strong>人口:</strong> ${planet.population}</p>
                    <p><strong>建筑:</strong></p>
                    <ul>
                        ${buildingList}
                    </ul>
                    <div style="margin:6px 0; font-size:12px; color:#ccc;">
                        <span>当前己方在此舰船艘数：<strong style="color:#00ff88;">${myShipsHere}</strong></span>
                        <span style="margin-left:8px;">强袭阈值：>${desperateThreshold} 艘</span>
                        <div style="color:#aaa;">提示：当己方没有任何行星时，若在一颗星球集结的己方舰船总数超过该阈值，可尝试强袭占领（受停战/护盾限制）。</div>
                        ${assaultAlways ? '<div style="color:#ffb199;">您拥有“强袭特权”（停战结束后，舰队数量最多的势力可持续强袭）。</div>' : ''}
                        ${assaultInfoHtml}
                    </div>
                    ${canAssault ? `<button id="btn-assault" style="margin-top:8px;background:linear-gradient(135deg,#ff6a6a 0%, #ff9a3c 100%);">强袭占领（背城一击）</button>` : ''}
                    ${canRename ? `<div style="margin:10px 0; padding:8px; background:rgba(0,0,0,0.2); border-radius:6px;">
                        <h3>分派：己方驻军/巡逻上限</h3>
                        <div style="display:flex; align-items:center; gap:6px; margin:6px 0;">
                            <label style=\"min-width:120px;\">本星球驻军上限</label>
                            <input id=\"cap-planet\" type=\"number\" min=\"0\" placeholder=\"上限\" value=\"${myCap}\" style=\"width:90px;\" />
                            <button id=\"cap-planet-save\" style=\"width:auto; padding:6px 10px;\">保存</button>
                        </div>
                        <div style=\"margin-top:6px;\">
                            <label style=\"display:block; margin-bottom:4px;\">相邻连线巡逻上限</label>
                            ${edgeRows || '<small>无相邻连线</small>'}
                        </div>
                        <small style=\"display:block;color:#aaaacc;\">说明：仅限制己方舰队数量，不影响其他势力。</small>
                    </div>` : ''}
                    <p><strong>产出:</strong></p>
                    <ul>
                        <li>能量: ${planet.resource_production.energy.toFixed(1)}</li>
                        <li>矿物: ${planet.resource_production.minerals.toFixed(1)}</li>
                        <li>科研: ${planet.resource_production.research.toFixed(1)}</li>
                    </ul>
                    ${colonizeButton}
                    ${renameControls}
                    <p><strong>连接星球:</strong></p>
                    <ul>
                        ${connectedList}
                    </ul>
                `;

                // 绑定强袭事件（后端需提供 /api/planet/assault）
                const assaultBtn = document.getElementById('btn-assault');
                if (assaultBtn) {
                    assaultBtn.addEventListener('click', async () => {
                        try {
                            const resp = await fetch('/api/planet/assault', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ planet_id: planet.id, faction_id: 'player' })});
                            const d = await resp.json();
                            if (d.success) { alert('强袭结算完成'); this.updateUI(); this.selectPlanet(planet.id); }
                            else { alert('强袭失败：' + (d.message||'未知错误')); }
                        } catch (err) {
                            alert('网络错误：' + err.message);
                        }
                    });
                }

                if (canColonize) {
                    const button = document.getElementById('colonize-now-btn');
                    button.addEventListener('click', () => {
                        this.colonizeSelectedPlanet(planetId, directOption.fromId);
                    });
                }

                if (canRename) {
                    const renameBtn = document.getElementById('rename-btn');
                    const renameInput = document.getElementById('rename-input');
                    if (renameBtn && renameInput) {
                        renameBtn.addEventListener('click', async () => {
                            const newName = (renameInput.value || '').trim();
                            if (!newName) { alert('请输入新名称'); return; }
                            try {
                                const resp = await fetch('/api/game/planet_rename', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ planet_id: planetId, new_name: newName })
                                });
                                const d = await resp.json();
                                if (d.success) {
                                    // 更新本地状态并刷新
                                    if (this.gameState && this.gameState.planets && d.planet) {
                                        this.gameState.planets[planetId] = d.planet;
                                    }
                                    alert('重命名成功');
                                    this.updateUI();
                                    this.updatePlanetDetails(planetId);
                                    this.render();
                                } else {
                                    alert('重命名失败：' + (d.message || '未知错误'));
                                }
                            } catch (e) {
                                alert('网络错误：' + e.message);
                            }
                        });
                    }

                    // 保存本星球驻军上限
                    const capBtn = document.getElementById('cap-planet-save');
                    const capInput = document.getElementById('cap-planet');
                    if (capBtn && capInput) {
                        capBtn.addEventListener('click', async () => {
                            const val = parseInt(capInput.value || '0', 10);
                            const resp = await fetch('/api/alloc/planet', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ owner:'player', planet_id: planetId, cap: val })});
                            const d = await resp.json();
                            if (d.success) { alert('已保存驻军上限'); this.updateUI(); this.updatePlanetDetails(planetId); }
                            else { alert('保存失败：' + (d.message || '未知错误')); }
                        });
                    }
                    // 保存相邻连线巡逻上限
                    detailsDiv.querySelectorAll('.edge-cap-save').forEach(btn => {
                        btn.addEventListener('click', async () => {
                            const a = btn.getAttribute('data-a');
                            const b = btn.getAttribute('data-b');
                            const input = detailsDiv.querySelector(`.edge-cap-input[data-a="${a}"][data-b="${b}"]`);
                            const val = parseInt((input && input.value) || '0', 10);
                            const resp = await fetch('/api/alloc/edge', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ owner:'player', a, b, cap: val })});
                            const d = await resp.json();
                            if (d.success) { alert('已保存巡逻上限'); this.updateUI(); this.updatePlanetDetails(planetId); }
                            else { alert('保存失败：' + (d.message || '未知错误')); }
                        });
                    });
                }
            }
        } catch (error) {
            console.error('Failed to get planet details:', error);
        }
    }

    prefillColonizeSelection(planetId) {
        const select = document.getElementById('param-colonize-target');
        if (!select) return;
        const candidates = this.getColonizationCandidates();
        const match = candidates.find(opt => opt.targetId === planetId);
        if (match) {
            select.value = `${match.fromId}|${match.targetId}`;
        }
    }

    async colonizeSelectedPlanet(planetId, presetFromId = null) {
        if (!this.gameState || !this.gameState.factions['player']) {
            alert('当前无法执行殖民。');
            return;
        }

        const playerFaction = this.gameState.factions['player'];
        let fromId = presetFromId;

        if (!fromId) {
            const neighbors = this.getAdjacentPlanets(planetId);
            let best = null;
            neighbors.forEach(pid => {
                if (!playerFaction.planets.includes(pid)) return;
                const planet = this.gameState.planets[pid];
                const population = planet ? planet.population : 0;
                if (!best || population > best.population) {
                    best = { id: pid, population };
                }
            });
            fromId = best ? best.id : null;
        }

        if (!fromId) {
            alert('该星球与您的势力未连通，无法直接殖民。');
            return;
        }

        try {
            const data = await this.postCommand('colonize', {
                from_planet: fromId,
                to_planet: planetId
            });
            if (data.success) {
                alert('殖民指令已提交！');
                this.prefillColonizeSelection(planetId);
            } else {
                alert('殖民失败: ' + data.message);
            }
        } catch (error) {
            alert('错误: ' + error.message);
        }
    }
    
    render() {
        if (!this.gameState) return;
        
        const ctx = this.ctx;
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        // 背景：优先绘制自定义背景图，否则绘制星空点
        if (this.bgImage) {
            const img = this.bgImage;
            const cw = this.canvas.width;
            const ch = this.canvas.height;
            const iw = img.width;
            const ih = img.height;
            // cover 填充
            const scale = Math.max(cw / iw, ch / ih);
            const dw = iw * scale;
            const dh = ih * scale;
            const dx = (cw - dw) / 2;
            const dy = (ch - dh) / 2;
            ctx.globalAlpha = 0.9;
            ctx.drawImage(img, dx, dy, dw, dh);
            ctx.globalAlpha = 1;
        } else {
            // Draw background stars
            ctx.fillStyle = '#ffffff';
            for (let i = 0; i < 200; i++) {
                const x = (i * 1234.5) % this.canvas.width;
                const y = (i * 5678.9) % this.canvas.height;
                const size = (i % 3) * 0.5;
                ctx.fillRect(x, y, size, size);
            }
        }
        
        // Draw connections
        const selectedNeighbors = this.selectedPlanet ? new Set(this.getAdjacentPlanets(this.selectedPlanet)) : null;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([12, 14]);
        ctx.lineDashOffset = -this.connectionPhase;
        for (const conn of this.gameState.connections) {
            const p1 = this.gameState.planets[conn[0]];
            const p2 = this.gameState.planets[conn[1]];
            const pos1 = this.worldToScreen(p1.position[0], p1.position[1]);
            const pos2 = this.worldToScreen(p2.position[0], p2.position[1]);

            let strokeColor = 'rgba(100, 120, 200, 0.25)';
            if (p1.owner && p2.owner && p1.owner === p2.owner) {
                strokeColor = this.toRGBA(this.getFactionColor(p1.owner), 0.4);
            } else if (p1.owner === 'player' || p2.owner === 'player') {
                strokeColor = 'rgba(0, 212, 255, 0.45)';
            }
            if (this.selectedPlanet && (conn[0] === this.selectedPlanet || conn[1] === this.selectedPlanet || (selectedNeighbors && (selectedNeighbors.has(conn[0]) || selectedNeighbors.has(conn[1]))))) {
                strokeColor = this.toRGBA('#ffff66', 0.6);
                ctx.lineWidth = 2.2;
            } else {
                ctx.lineWidth = 1.5;
            }

            ctx.strokeStyle = strokeColor;
            ctx.beginPath();
            ctx.moveTo(pos1.x, pos1.y);
            ctx.lineTo(pos2.x, pos2.y);
            ctx.stroke();
        }
        ctx.setLineDash([]);
        ctx.lineWidth = 1;
        
        // Draw planets
        for (const [planetId, planet] of Object.entries(this.gameState.planets)) {
            const pos = this.worldToScreen(planet.position[0], planet.position[1]);
            
            // Planet color based on owner
            const color = planet.owner ? this.getFactionColor(planet.owner) : '#888888';

            // Highlight selected planet
            if (planetId === this.selectedPlanet) {
                ctx.strokeStyle = '#ffff88';
                ctx.lineWidth = 3;
                ctx.beginPath();
                ctx.arc(pos.x, pos.y, 12, 0, Math.PI * 2);
                ctx.stroke();
            }
            
            // Draw planet
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(pos.x, pos.y, 8, 0, Math.PI * 2);
            ctx.fill();
            
            // Draw planet name
            ctx.fillStyle = '#ffffff';
            ctx.font = '10px Arial';
            ctx.textAlign = 'center';
            ctx.fillText(planet.name, pos.x, pos.y - 15);
        }
        
        // Draw fleets as rectangles near planet
        for (const fleet of Object.values(this.gameState.fleets)) {
            const planet = this.gameState.planets[fleet.position];
            if (!planet) continue;
            const pos = this.worldToScreen(planet.position[0], planet.position[1]);
            const color = this.toRGBA(this.getFactionColor(fleet.owner), fleet.owner === 'player' ? 0.9 : 0.8);
            ctx.fillStyle = color;
            const w = 12, h = 6;
            ctx.fillRect(pos.x - w/2, pos.y + 10, w, h);
            ctx.strokeStyle = '#101010';
            ctx.lineWidth = 1;
            ctx.strokeRect(pos.x - w/2, pos.y + 10, w, h);
            // 显示熟练度
            if (typeof fleet.proficiency === 'number') {
                ctx.fillStyle = '#ffeeaa';
                ctx.font = '10px Arial';
                ctx.textAlign = 'left';
                ctx.fillText(`熟练 ${Math.floor(fleet.proficiency)}%`, pos.x + 8, pos.y + 16);
            }
        }

        // Draw patrol fleets at edge midpoints
        for (const fleet of Object.values(this.gameState.fleets)) {
            if (!fleet.patrol_edge) continue;
            const [a, b] = fleet.patrol_edge;
            const pa = this.gameState.planets[a];
            const pb = this.gameState.planets[b];
            if (!pa || !pb) continue;
            const sa = this.worldToScreen(pa.position[0], pa.position[1]);
            const sb = this.worldToScreen(pb.position[0], pb.position[1]);
            const mx = (sa.x + sb.x) / 2;
            const my = (sa.y + sb.y) / 2;
            const color = this.toRGBA(this.getFactionColor(fleet.owner), 0.9);
            ctx.fillStyle = color;
            const w = 14, h = 7;
            ctx.fillRect(mx - w/2, my - h/2, w, h);
            ctx.strokeStyle = '#111';
            ctx.lineWidth = 1;
            ctx.strokeRect(mx - w/2, my - h/2, w, h);
        }

        // 若有选中舰队，突出显示其相邻星球作为可点击目的地
        if (this.selectedFleetId && this.highlightNeighbors && this.highlightNeighbors.size > 0) {
            ctx.save();
            ctx.strokeStyle = 'rgba(255, 255, 102, 0.9)';
            ctx.lineWidth = 3;
            for (const pid of this.highlightNeighbors) {
                const p = this.gameState.planets[pid];
                if (!p) continue;
                const spos = this.worldToScreen(p.position[0], p.position[1]);
                ctx.beginPath();
                ctx.arc(spos.x, spos.y, 14, 0, Math.PI * 2);
                ctx.stroke();
                // 目的地名称标签
                ctx.fillStyle = '#ffff99';
                ctx.font = '11px Arial';
                ctx.textAlign = 'center';
                ctx.fillText(p.name || pid, spos.x, spos.y + 28);
            }
            ctx.restore();
        }

        // 绘制舰队拖拽指引线
        if (this._dragState?.active && this._dragState.fleetId) {
            const f = this.gameState.fleets[this._dragState.fleetId];
            if (f) {
                const p = this.gameState.planets[f.position];
                if (p) {
                    const s = this.worldToScreen(p.position[0], p.position[1]);
                    const start = { x: s.x, y: s.y + 13 };
                    const cur = this._dragState.cur;
                    ctx.save();
                    ctx.strokeStyle = 'rgba(255,255,180,0.9)';
                    ctx.lineWidth = 2;
                    ctx.setLineDash([6, 6]);
                    ctx.beginPath();
                    ctx.moveTo(start.x, start.y);
                    ctx.lineTo(cur.x, cur.y);
                    ctx.stroke();
                    ctx.setLineDash([]);
                    ctx.restore();
                }
            }
        }
    }
    
    worldToScreen(worldX, worldY) {
        return {
            x: this.camera.x + worldX * this.camera.zoom * 0.5,
            y: this.camera.y + worldY * this.camera.zoom * 0.5
        };
    }

    _hitTestFleet(x, y) {
        if (!this.gameState || !this.gameState.fleets) return null;
        for (const f of Object.values(this.gameState.fleets)) {
            const p = this.gameState.planets[f.position];
            if (!p) continue;
            const s = this.worldToScreen(p.position[0], p.position[1]);
            const w = 12, h = 6;
            const rx = s.x - w/2, ry = s.y + 10;
            if (x >= rx && x <= rx + w && y >= ry && y <= ry + h) {
                return f.id;
            }
        }
        return null;
    }

    async _handleFleetDragDrop() {
        const fid = this._dragState?.fleetId;
        if (!fid || !this.gameState || !this.gameState.fleets[fid]) return;
        const f = this.gameState.fleets[fid];
        // 释放到相邻星球？
        const pid = this._pickPlanet(this._dragState.cur.x, this._dragState.cur.y);
        if (pid && pid !== f.position) {
            const neighbors = this.connectionCache[f.position] || this.getAdjacentPlanets(f.position);
            if (neighbors.includes(pid)) {
                const resp = await fetch('/api/fleet/drag', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ owner: 'player', fleet_id: fid, target: { type: 'planet', planet_id: pid } })
                });
                const d = await resp.json();
                if (d.success) { this.updateUI(); }
                else { alert('移动失败：' + (d.message || '未知错误')); }
                return;
            }
        }
        // 释放到边中点？
        const edge = this._pickEdgeMidpoint(this._dragState.cur.x, this._dragState.cur.y);
        if (edge) {
            const [a, b] = edge;
            const resp = await fetch('/api/fleet/drag', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ owner: 'player', fleet_id: fid, target: { type: 'edge', a, b } })
            });
            const d = await resp.json();
            if (d.success) { this.updateUI(); }
            else { alert('设置巡逻失败：' + (d.message || '未知错误')); }
            return;
        }
    }

    _pickPlanet(x, y) {
        if (!this.gameState || !this.gameState.planets) return null;
        for (const [pid, p] of Object.entries(this.gameState.planets)) {
            const s = this.worldToScreen(p.position[0], p.position[1]);
            const dist = Math.hypot(x - s.x, y - s.y);
            if (dist <= 16) return pid;
        }
        return null;
    }

    _pickEdgeMidpoint(x, y) {
        if (!this.gameState || !this.gameState.connections) return null;
        const threshold = 12;
        for (const conn of this.gameState.connections) {
            const [a, b] = conn;
            const pa = this.gameState.planets[a];
            const pb = this.gameState.planets[b];
            if (!pa || !pb) continue;
            const sa = this.worldToScreen(pa.position[0], pa.position[1]);
            const sb = this.worldToScreen(pb.position[0], pb.position[1]);
            const mx = (sa.x + sb.x) / 2; const my = (sa.y + sb.y) / 2;
            if (Math.hypot(x - mx, y - my) <= threshold) return [a, b];
        }
        return null;
    }
    
    screenToWorld(screenX, screenY) {
        return {
            x: (screenX - this.camera.x) / (this.camera.zoom * 0.5),
            y: (screenY - this.camera.y) / (this.camera.zoom * 0.5)
        };
    }
    
    onMouseDown(e) {
        this.isDragging = true;
        this.lastMousePos = { x: e.clientX, y: e.clientY };
        // 若点击在某支舰队矩形上，则进入舰队拖拽模式
        if (this.gameState) {
            const rect = this.canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const hitId = this._hitTestFleet?.(x, y);
            if (hitId) {
                this._dragState.active = true;
                this._dragState.fleetId = hitId;
                this._dragState.start = { x, y };
                this._dragState.cur = { x, y };
                return;
            }
        }
        // 检测是否按在某个星球上，若是则进入节点拖拽
        if (this.gameState) {
            const rect = this.canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            for (const [planetId, planet] of Object.entries(this.gameState.planets)) {
                const pos = this.worldToScreen(planet.position[0], planet.position[1]);
                const dist = Math.hypot(x - pos.x, y - pos.y);
                if (dist < 12) {
                    this.draggingNode = planetId;
                    break;
                }
            }
        }
    }
    
    onMouseMove(e) {
        if (!this.isDragging) return;
        const dx = e.clientX - this.lastMousePos.x;
        const dy = e.clientY - this.lastMousePos.y;
        this.lastMousePos = { x: e.clientX, y: e.clientY };
        if (this._dragState?.active) {
            const rect = this.canvas.getBoundingClientRect();
            this._dragState.cur = { x: e.clientX - rect.left, y: e.clientY - rect.top };
            this.render();
            return;
        }
        if (this.draggingNode && this.gameState) {
            // 将屏幕位移反投影到世界坐标
            const p = this.gameState.planets[this.draggingNode];
            const worldDx = dx / (this.camera.zoom * 0.5);
            const worldDy = dy / (this.camera.zoom * 0.5);
            p.position = [p.position[0] + worldDx, p.position[1] + worldDy];
            this.render();
        } else {
            this.camera.x += dx;
            this.camera.y += dy;
            this.render();
        }
    }
    
    onMouseUp(e) {
        this.isDragging = false;
        if (this._dragState?.active) {
            const rect = this.canvas.getBoundingClientRect();
            this._dragState.cur = { x: e.clientX - rect.left, y: e.clientY - rect.top };
            this._handleFleetDragDrop?.().finally(() => {
                this._dragState = { active: false, fleetId: null, start: { x: 0, y: 0 }, cur: { x: 0, y: 0 } };
                this.render();
            });
            return;
        }
        if (this.draggingNode && this.gameState) {
            const pid = this.draggingNode;
            const p = this.gameState.planets[pid];
            // 提交保存（可忽略失败）
            fetch('/api/game/planet_position', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: pid, x: p.position[0], y: p.position[1] })
            }).catch(()=>{});
        }
        this.draggingNode = null;
    }
    
    onWheel(e) {
        e.preventDefault();
        const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
        this.camera.zoom *= zoomFactor;
        this.camera.zoom = Math.max(0.5, Math.min(3, this.camera.zoom));
        this.render();
    }
    
    onClick(e) {
        if (!this.gameState) return;
        
        const rect = this.canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        
        // Find clicked planet
        for (const [planetId, planet] of Object.entries(this.gameState.planets)) {
            const pos = this.worldToScreen(planet.position[0], planet.position[1]);
            const dist = Math.sqrt((x - pos.x) ** 2 + (y - pos.y) ** 2);
            if (dist < 15) {
                if (this.selectedFleetId && this.highlightNeighbors && this.highlightNeighbors.has(planetId)) {
                    this.issueMoveTo(planetId);
                    return;
                }
                this.selectPlanet(planetId);
                break;
            }
        }
    }

    _showPlanetTooltip(e) {
        if (!this.gameState) return;
        const rect = this.canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const tooltip = document.getElementById('tooltip');
        let found = null;
        for (const [planetId, planet] of Object.entries(this.gameState.planets)) {
            const pos = this.worldToScreen(planet.position[0], planet.position[1]);
            const dist = Math.hypot(x - pos.x, y - pos.y);
            if (dist < 14) { found = { planetId, planet }; break; }
        }
        if (!found) { if (tooltip) tooltip.style.display = 'none'; return; }
        const planet = found.planet;
        const bnames = (planet.buildings||[]).map(b => BUILDING_NAME_MAP[b] || b);
        const prod = planet.resource_production || { energy:0, minerals:0, research:0 };
        tooltip.innerHTML = `
            <div style="min-width:180px;">
                <div style="font-weight:bold; color:#00d4ff;">${planet.name}</div>
                <div style="margin-top:4px; color:#ccc;">建筑：${bnames.length? bnames.join('、') : '无'}</div>
                <div style="margin-top:4px; color:#aaa;">产出 E:${Math.floor(prod.energy||0)} M:${Math.floor(prod.minerals||0)} R:${Math.floor(prod.research||0)}</div>
            </div>`;
        tooltip.style.left = (e.clientX + 12) + 'px';
        tooltip.style.top = (e.clientY + 12) + 'px';
        tooltip.style.display = 'block';
    }

    async _autoLoopTurns() {
        const chk = document.getElementById('auto-end-turn');
        // 防抖：避免多重循环
        if (this._autoRunning) return;
        this._autoRunning = true;
        try {
            while (chk && chk.checked) {
                await this.endTurn();
                if (!this.gameState || (this.gameState.game_over && !this.gameState.allow_postgame)) break;
                // 微小延迟，避免阻塞UI/请求过快
                await new Promise(r => setTimeout(r, 15000));
            }
        } finally {
            this._autoRunning = false;
        }
    }
    
    setSelectedFleet(fleetId) {
        this.selectedFleetId = fleetId || null;
        this.highlightNeighbors.clear();
        if (!fleetId || !this.gameState || !this.gameState.fleets[fleetId]) { this.updateMoveModeBanner(); this.render(); return; }
        const fleet = this.gameState.fleets[fleetId];
        const neighbors = this.connectionCache[fleet.position] || this.getAdjacentPlanets(fleet.position);
        neighbors.forEach(pid => this.highlightNeighbors.add(pid));
        if (fleet.position) this.selectPlanet(fleet.position);
        this.updateMoveModeBanner();
        this.render();
    }

    async issueMoveTo(destinationPid) {
        if (!this.selectedFleetId) return;
        try {
            const resp = await fetch('/api/fleet/move', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ owner:'player', fleet_id: this.selectedFleetId, destination: destinationPid })});
            const d = await resp.json();
            if (d.success) {
                alert('已下达移动命令');
                this.selectedFleetId = null;
                this.highlightNeighbors.clear();
                this.updateMoveModeBanner();
                this.updateUI();
            } else {
                alert('移动失败：' + d.message);
            }
        } catch (e) {
            alert('网络错误：' + e.message);
        }
    }

    updateMoveModeBanner() {
        if (!this._bannerEl) {
            const el = document.createElement('div');
            el.id = 'move-mode-banner';
            el.style.position = 'fixed';
            el.style.left = '50%';
            el.style.top = '12px';
            el.style.transform = 'translateX(-50%)';
            el.style.background = 'rgba(0,0,0,0.6)';
            el.style.color = '#ffffcc';
            el.style.padding = '6px 12px';
            el.style.border = '1px solid #ffff66';
            el.style.borderRadius = '6px';
            el.style.zIndex = '1000';
            el.style.fontSize = '12px';
            el.style.display = 'none';
            const cancelBtn = document.createElement('button');
            cancelBtn.textContent = '取消选择 (Esc)';
            cancelBtn.style.marginLeft = '10px';
            cancelBtn.style.cursor = 'pointer';
            cancelBtn.addEventListener('click', () => this.setSelectedFleet(null));
            el.appendChild(document.createTextNode('移动模式：点击高亮星球下达目的地'));
            el.appendChild(cancelBtn);
            document.body.appendChild(el);
            this._bannerEl = el;
        }
        if (this.selectedFleetId && this.highlightNeighbors.size > 0) {
            this._bannerEl.style.display = 'block';
        } else if (this._bannerEl) {
            this._bannerEl.style.display = 'none';
        }
    }
    
    showLoading(show) {
        document.getElementById('loading').style.display = show ? 'block' : 'none';
    }
}

// Initialize game
const game = new GalaxyGame();
