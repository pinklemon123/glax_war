// Game client JavaScript
class GalaxyGame {
    constructor() {
        this.canvas = document.getElementById('galaxy-canvas');
        this.ctx = this.canvas.getContext('2d');
        this.gameState = null;
        this.selectedPlanet = null;
        this.camera = { x: 0, y: 0, zoom: 1 };
        this.isDragging = false;
        this.lastMousePos = { x: 0, y: 0 };
        
        this.initCanvas();
        this.initEventListeners();
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
        
        // Canvas interaction
        this.canvas.addEventListener('mousedown', (e) => this.onMouseDown(e));
        this.canvas.addEventListener('mousemove', (e) => this.onMouseMove(e));
        this.canvas.addEventListener('mouseup', () => this.onMouseUp());
        this.canvas.addEventListener('wheel', (e) => this.onWheel(e));
        this.canvas.addEventListener('click', (e) => this.onClick(e));
        
        // Command panel
        document.getElementById('command-type').addEventListener('change', (e) => {
            this.updateCommandParams(e.target.value);
        });
        
        document.getElementById('submit-command-btn').addEventListener('click', () => {
            this.submitCommand();
        });
    }
    
    async newGame() {
        this.showLoading(true);
        try {
            const response = await fetch('/api/game/new?planets=30&ai=3');
            const data = await response.json();
            if (data.success) {
                this.gameState = data.game_state;
                this.updateUI();
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
                this.updateUI();
                this.render();
            } else {
                alert('结束回合失败: ' + data.message);
            }
        } catch (error) {
            alert('错误: ' + error.message);
        } finally {
            this.showLoading(false);
        }
    }
    
    async submitCommand() {
        const commandType = document.getElementById('command-type').value;
        if (!commandType) return;
        
        const params = this.getCommandParams(commandType);
        if (!params) return;
        
        try {
            const response = await fetch('/api/game/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    faction_id: 'player',
                    command_type: commandType,
                    parameters: params
                })
            });
            const data = await response.json();
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
    
    getCommandParams(commandType) {
        const params = {};
        
        if (commandType === 'colonize') {
            const from = document.getElementById('param-from').value;
            const to = document.getElementById('param-to').value;
            if (!from || !to) {
                alert('请填写所有参数');
                return null;
            }
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
        }
        
        return params;
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
            container.innerHTML = `
                <label>从星球:</label>
                <select id="param-from">
                    ${playerFaction.planets.map(p => `<option value="${p}">${this.gameState.planets[p].name}</option>`).join('')}
                </select>
                <label>到星球:</label>
                <input type="text" id="param-to" placeholder="目标星球ID">
            `;
        } else if (commandType === 'build') {
            container.innerHTML = `
                <label>星球:</label>
                <select id="param-planet">
                    ${playerFaction.planets.map(p => `<option value="${p}">${this.gameState.planets[p].name}</option>`).join('')}
                </select>
                <label>建筑类型:</label>
                <select id="param-building">
                    <option value="energy_plant">能量工厂</option>
                    <option value="mining_station">采矿站</option>
                    <option value="research_lab">研究实验室</option>
                    <option value="shipyard">船坞</option>
                    <option value="defense_station">防御站</option>
                </select>
            `;
        } else if (commandType === 'research') {
            const availableTechs = Object.keys(this.gameState.technologies).filter(
                t => !playerFaction.technologies.includes(t)
            );
            container.innerHTML = `
                <label>科技:</label>
                <select id="param-tech">
                    ${availableTechs.map(t => `<option value="${t}">${t}</option>`).join('')}
                </select>
            `;
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
    }
    
    selectPlanet(planetId) {
        this.selectedPlanet = planetId;
        this.updatePlanetDetails(planetId);
        this.render();
    }
    
    async updatePlanetDetails(planetId) {
        try {
            const response = await fetch(`/api/game/planet/${planetId}`);
            const data = await response.json();
            if (data.success) {
                const planet = data.planet;
                const detailsDiv = document.getElementById('planet-details');
                detailsDiv.innerHTML = `
                    <h3>${planet.name}</h3>
                    <p><strong>类型:</strong> ${planet.type}</p>
                    <p><strong>所有者:</strong> ${planet.owner || '无'}</p>
                    <p><strong>人口:</strong> ${planet.population}</p>
                    <p><strong>建筑:</strong></p>
                    <ul>
                        ${planet.buildings.map(b => `<li>${b}</li>`).join('') || '<li>无</li>'}
                    </ul>
                    <p><strong>产出:</strong></p>
                    <ul>
                        <li>能量: ${planet.resource_production.energy.toFixed(1)}</li>
                        <li>矿物: ${planet.resource_production.minerals.toFixed(1)}</li>
                        <li>科研: ${planet.resource_production.research.toFixed(1)}</li>
                    </ul>
                    <p><strong>连接星球:</strong></p>
                    <ul>
                        ${data.connected_planets.map(p => {
                            const connPlanet = this.gameState.planets[p];
                            return `<li onclick="game.selectPlanet('${p}')" style="cursor:pointer; color: #00d4ff;">${connPlanet.name}</li>`;
                        }).join('')}
                    </ul>
                `;
            }
        } catch (error) {
            console.error('Failed to get planet details:', error);
        }
    }
    
    render() {
        if (!this.gameState) return;
        
        const ctx = this.ctx;
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        // Draw background stars
        ctx.fillStyle = '#ffffff';
        for (let i = 0; i < 200; i++) {
            const x = (i * 1234.5) % this.canvas.width;
            const y = (i * 5678.9) % this.canvas.height;
            const size = (i % 3) * 0.5;
            ctx.fillRect(x, y, size, size);
        }
        
        // Draw connections
        ctx.strokeStyle = 'rgba(100, 100, 150, 0.3)';
        ctx.lineWidth = 1;
        for (const conn of this.gameState.connections) {
            const p1 = this.gameState.planets[conn[0]];
            const p2 = this.gameState.planets[conn[1]];
            const pos1 = this.worldToScreen(p1.position[0], p1.position[1]);
            const pos2 = this.worldToScreen(p2.position[0], p2.position[1]);
            ctx.beginPath();
            ctx.moveTo(pos1.x, pos1.y);
            ctx.lineTo(pos2.x, pos2.y);
            ctx.stroke();
        }
        
        // Draw planets
        for (const [planetId, planet] of Object.entries(this.gameState.planets)) {
            const pos = this.worldToScreen(planet.position[0], planet.position[1]);
            
            // Planet color based on owner
            let color = '#888888';
            if (planet.owner === 'player') {
                color = '#00ff88';
            } else if (planet.owner) {
                color = '#ff4444';
            }
            
            // Highlight selected planet
            if (planetId === this.selectedPlanet) {
                ctx.strokeStyle = '#ffff00';
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
        
        // Draw fleets
        for (const fleet of Object.values(this.gameState.fleets)) {
            const planet = this.gameState.planets[fleet.position];
            if (!planet) continue;
            
            const pos = this.worldToScreen(planet.position[0], planet.position[1]);
            
            // Fleet color based on owner
            let color = '#ffffff';
            if (fleet.owner === 'player') {
                color = '#00ffff';
            } else {
                color = '#ff88ff';
            }
            
            // Draw fleet indicator
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.moveTo(pos.x, pos.y + 15);
            ctx.lineTo(pos.x - 5, pos.y + 22);
            ctx.lineTo(pos.x + 5, pos.y + 22);
            ctx.closePath();
            ctx.fill();
        }
    }
    
    worldToScreen(worldX, worldY) {
        return {
            x: this.camera.x + worldX * this.camera.zoom * 0.5,
            y: this.camera.y + worldY * this.camera.zoom * 0.5
        };
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
    }
    
    onMouseMove(e) {
        if (this.isDragging) {
            const dx = e.clientX - this.lastMousePos.x;
            const dy = e.clientY - this.lastMousePos.y;
            this.camera.x += dx;
            this.camera.y += dy;
            this.lastMousePos = { x: e.clientX, y: e.clientY };
            this.render();
        }
    }
    
    onMouseUp() {
        this.isDragging = false;
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
                this.selectPlanet(planetId);
                break;
            }
        }
    }
    
    showLoading(show) {
        document.getElementById('loading').style.display = show ? 'block' : 'none';
    }
}

// Initialize game
const game = new GalaxyGame();
