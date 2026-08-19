"""Authoritative two-player tank game server."""

import json
import math
import random
import socket
import threading
import time

HOST = "0.0.0.0"
PORT = 5555
WIDTH, HEIGHT = 1470, 956
TANK_SIZE = 42
MAX_HEALTH = 12
DRONE_MAX_HEALTH = 4
DRONE_SPLASH_RADIUS = 150
EXPLOSION_DURATION = 0.18
TANK_SPEED = 185.0
TURN_SPEED = 2.8
ROUND_SECONDS = 180
WEAPONS = {
	"cannon": {"cooldown": 0.55, "speed": 520.0, "damage": 1, "count": 1, "spread": 0.0, "radius": 5},
	"machine": {"cooldown": 0.065, "speed": 600.0, "damage": 0.25, "count": 1, "spread": 0.1, "radius": 3},
	"shotgun": {"cooldown": 0.9, "speed": 450.0, "damage": 1, "count": 5, "spread": 0.22, "radius": 4},
	"drone": {"cooldown": 1.3, "speed": 290.0, "damage": 2, "count": 1, "spread": 0.0, "radius": 8},
	"rocket_launcher": {"cooldown": 1.1, "speed": 520.0, "damage": 1, "count": 6, "spread": 0.0, "radius": 5},
	"portal": {"cooldown": 0.8, "speed": 700.0, "damage": 1.0, "count": 1, "spread": 0.0, "radius": 7},
}
SPAWNS = [(70.0, HEIGHT / 2), (WIDTH - 112.0, HEIGHT / 2)]
WALLS = [(210, 100, 300, 24), (760, 90, 24, 230), (1080, 110, 280, 24),
		 (120, 300, 24, 260), (360, 300, 250, 24), (700, 390, 300, 24),
		 (1160, 330, 24, 260), (180, 650, 280, 24), (540, 610, 24, 210),
		 (790, 700, 300, 24), (1180, 750, 24, 150), (300, 850, 280, 24)]
MACHINE_BOUNCE_CHANCE = 0.25


def intersects_wall(x, y):
	return any(x < wall[0] + wall[2] and x + TANK_SIZE > wall[0]
			   and y < wall[1] + wall[3] and y + TANK_SIZE > wall[1]
			   for wall in WALLS)


class TankServer:
	def __init__(self):
		self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.clients = {}
		self.players = {}
		self.bullets = []
		self.explosions = []
		self.lock = threading.Lock()
		self.running = True
		self.round_started = None
		self.winner = None

	def start(self):
		self.server_socket.bind((HOST, PORT))
		self.server_socket.listen(2)
		print(f"Tank server listening on port {PORT}")
		print("Share this computer's LAN IP with both players.")
		threading.Thread(target=self.game_loop, daemon=True).start()
		while self.running:
			try:
				conn, address = self.server_socket.accept()
				with self.lock:
					if len(self.players) >= 2:
						conn.sendall(b'{"error":"The match is full."}\n')
						conn.close()
						continue
					player_id = str(len(self.players) + 1)
					x, y = SPAWNS[len(self.players)]
					self.players[player_id] = {"x": x, "y": y, "angle": 0.0 if player_id == "1" else math.pi,
						"health": MAX_HEALTH, "connected": True, "weapon": "cannon", "drone_active": False}
					self.clients[player_id] = conn
				print(f"Player {player_id} joined from {address[0]}")
				conn.sendall((json.dumps({"type": "welcome", "id": player_id}) + "\n").encode())
				threading.Thread(target=self.handle_client, args=(conn, player_id), daemon=True).start()
				if len(self.players) == 2:
					if self.winner:
						self.reset_round()
					else:
						self.round_started = time.monotonic()
					print("Both players joined. Round started.")
			except OSError:
				break

	def handle_client(self, conn, player_id):
		buffer = ""
		try:
			while True:
				chunk = conn.recv(4096)
				if not chunk:
					break
				buffer += chunk.decode("utf-8")
				while "\n" in buffer:
					line, buffer = buffer.split("\n", 1)
					if line.strip():
						self.apply_input(player_id, json.loads(line))
		except (ConnectionError, json.JSONDecodeError):
			pass
		finally:
			with self.lock:
				self.players.pop(player_id, None)
				self.clients.pop(player_id, None)
			conn.close()
			print(f"Player {player_id} disconnected")

	def apply_input(self, player_id, message):
		with self.lock:
			player = self.players.get(player_id)
			if not player:
				return
			if message.get("restart") and self.winner and len(self.players) == 2:
				self.reset_round()
				return
			player["input"] = message
			if self.winner:
				return
			if player.get("drone_active"):
				if message.get("detonate"):
					self.detonate_drone(player_id)
				return
			now = time.monotonic()
			weapon_name = message.get("weapon", "cannon")
			if weapon_name == "missile":
				weapon_name = "drone"
			weapon = WEAPONS.get(weapon_name, WEAPONS["cannon"])
			player["weapon"] = weapon_name if weapon_name in WEAPONS else "cannon"
			if message.get("fire") and now >= player.get("next_shot", 0):
				player["next_shot"] = now + weapon["cooldown"]
				if player["weapon"] == "drone":
					self.bullets.append({"owner": player_id, "x": player["x"] + TANK_SIZE / 2,
						"y": player["y"] + TANK_SIZE / 2, "angle": player["angle"],
						"speed": weapon["speed"], "damage": weapon["damage"],
						"health": DRONE_MAX_HEALTH, "max_health": DRONE_MAX_HEALTH,
						"radius": weapon["radius"], "weapon": "drone"})
					player["drone_active"] = True
					return
				if player["weapon"] == "rocket_launcher":
					enemy = next((other for other_id, other in self.players.items()
						if other_id != player_id), None)
					target_x = enemy["x"] + TANK_SIZE / 2 if enemy else player["x"] + math.cos(player["angle"]) * 100
					target_y = enemy["y"] + TANK_SIZE / 2 if enemy else player["y"] + math.sin(player["angle"]) * 100
					for side in (-1, 1):
						for longitudinal_offset in (-12, 0, 12):
							launch_x = player["x"] + TANK_SIZE / 2 + math.cos(player["angle"]) * longitudinal_offset
							launch_y = player["y"] + TANK_SIZE / 2 + math.sin(player["angle"]) * longitudinal_offset
							launch_x += -math.sin(player["angle"]) * side * (TANK_SIZE * 0.62)
							launch_y += math.cos(player["angle"]) * side * (TANK_SIZE * 0.62)
							rocket_angle = math.atan2(target_y - launch_y, target_x - launch_x)
							self.bullets.append({"owner": player_id, "x": launch_x, "y": launch_y,
								"angle": rocket_angle, "speed": weapon["speed"], "damage": weapon["damage"],
								"radius": weapon["radius"], "weapon": "rocket"})
					return
				for shot_index in range(weapon["count"]):
					if player["weapon"] == "machine":
						spread_offset = random.uniform(-weapon["spread"], weapon["spread"])
					elif weapon["count"] == 1:
						spread_offset = 0.0
					else:
						spread_offset = (shot_index - (weapon["count"] - 1) / 2) * weapon["spread"]
					self.bullets.append({"owner": player_id, "x": player["x"] + TANK_SIZE / 2,
						"y": player["y"] + TANK_SIZE / 2, "angle": player["angle"] + spread_offset,
						"speed": weapon["speed"], "damage": weapon["damage"], "radius": weapon["radius"],
						"weapon": player["weapon"]})

	def game_loop(self):
		previous = time.monotonic()
		while self.running:
			now = time.monotonic()
			delta = min(now - previous, 0.05)
			previous = now
			with self.lock:
				self.update_players(delta)
				self.update_bullets(delta)
				self.update_explosions(delta)
				payload = (json.dumps(self.snapshot(now)) + "\n").encode()
				connections = list(self.clients.items())
			for player_id, conn in connections:
				try:
					conn.sendall(payload)
				except OSError:
					self.players.pop(player_id, None)
			time.sleep(0.02)

	def update_players(self, delta):
		for player in self.players.values():
			if player.get("drone_active"):
				continue
			message = player.get("input", {})
			turn = max(-1, min(1, float(message.get("turn", 0))))
			throttle = max(-1, min(1, float(message.get("throttle", 0))))
			strafe = max(-1, min(1, float(message.get("strafe", 0))))
			player["angle"] += turn * TURN_SPEED * delta
			velocity_x = math.cos(player["angle"]) * throttle - math.sin(player["angle"]) * strafe
			velocity_y = math.sin(player["angle"]) * throttle + math.cos(player["angle"]) * strafe
			velocity_length = math.hypot(velocity_x, velocity_y) or 1
			new_x = max(0, min(WIDTH - TANK_SIZE, player["x"] + velocity_x / velocity_length * TANK_SPEED * delta))
			new_y = max(0, min(HEIGHT - TANK_SIZE, player["y"] + velocity_y / velocity_length * TANK_SPEED * delta))
			if not intersects_wall(new_x, player["y"]):
				player["x"] = new_x
			if not intersects_wall(player["x"], new_y):
				player["y"] = new_y

	def update_bullets(self, delta):
		survivors = []
		for bullet in self.bullets:
			if bullet["weapon"] == "drone":
				owner = self.players.get(bullet["owner"])
				if not owner or not owner.get("drone_active"):
					continue
				message = owner.get("input", {})
				bullet["angle"] += max(-1, min(1, float(message.get("turn", 0)))) * TURN_SPEED * delta
			bullet["x"] += math.cos(bullet["angle"]) * bullet["speed"] * delta
			bullet["y"] += math.sin(bullet["angle"]) * bullet["speed"] * delta
			if not (0 <= bullet["x"] <= WIDTH and 0 <= bullet["y"] <= HEIGHT):
				if bullet["weapon"] == "drone":
					self.explode_drone(bullet)
				continue
			if bullet["weapon"] != "portal" and any(
				wall[0] - bullet["radius"] <= bullet["x"] <= wall[0] + wall[2] + bullet["radius"]
				and wall[1] - bullet["radius"] <= bullet["y"] <= wall[1] + wall[3] + bullet["radius"]
				for wall in WALLS):
				if bullet["weapon"] == "drone":
					self.explode_drone(bullet)
				continue
			hit = False
			if bullet["weapon"] != "drone":
				for missile in self.bullets:
					if (missile["weapon"] == "drone" and missile["owner"] != bullet["owner"]
						and math.hypot(missile["x"] - bullet["x"], missile["y"] - bullet["y"]) <= missile["radius"] + bullet["radius"]):
						missile["health"] -= bullet["damage"]
						hit = True
						if missile["health"] <= 0:
							self.explode_drone(missile)
							self.bullets.remove(missile)
						break
				if hit:
					continue
			for player_id, player in self.players.items():
				if player_id == bullet["owner"]:
					continue
				if player["x"] <= bullet["x"] <= player["x"] + TANK_SIZE and player["y"] <= bullet["y"] <= player["y"] + TANK_SIZE:
					if bullet["weapon"] == "drone":
						self.explode_drone(bullet)
						hit = True
						break
					if bullet["weapon"] == "machine" and random.random() < MACHINE_BOUNCE_CHANCE:
						bullet["angle"] = (bullet["angle"] + math.pi
							+ random.uniform(-0.45, 0.45)) % (2 * math.pi)
						survivors.append(bullet)
						hit = True
						break
					player["health"] -= bullet["damage"]
					hit = True
					if player["health"] <= 0:
						self.winner = bullet["owner"]
					break
			if not hit:
				survivors.append(bullet)
		self.bullets = survivors

	def update_explosions(self, delta):
		for explosion in self.explosions:
			explosion["time_left"] -= delta
		self.explosions = [explosion for explosion in self.explosions
			if explosion["time_left"] > 0]

	def explode_drone(self, drone):
		owner_id = drone["owner"]
		owner = self.players.get(owner_id)
		if owner:
			owner["drone_active"] = False
		self.explosions.append({"x": drone["x"], "y": drone["y"],
			"radius": DRONE_SPLASH_RADIUS, "time_left": EXPLOSION_DURATION,
			"duration": EXPLOSION_DURATION})
		for player_id, player in self.players.items():
			if player_id == owner_id:
				continue
			if math.hypot(player["x"] + TANK_SIZE / 2 - drone["x"],
				player["y"] + TANK_SIZE / 2 - drone["y"]) <= DRONE_SPLASH_RADIUS:
				player["health"] -= drone["damage"]
				if player["health"] <= 0:
					self.winner = owner_id

	def detonate_drone(self, owner_id):
		drone = next((bullet for bullet in self.bullets
				if bullet["weapon"] == "drone" and bullet["owner"] == owner_id), None)
		if not drone:
			self.players[owner_id]["drone_active"] = False
			return
		self.explode_drone(drone)
		self.bullets.remove(drone)

	def reset_round(self):
		self.bullets.clear()
		self.explosions.clear()
		self.winner = None
		self.round_started = time.monotonic()
		for index, player_id in enumerate(sorted(self.players)):
			x, y = SPAWNS[index]
			player = self.players[player_id]
			player.update({"x": x, "y": y, "angle": 0.0 if index == 0 else math.pi,
				"health": MAX_HEALTH, "weapon": "cannon", "input": {}, "next_shot": 0,
				"drone_active": False})

	def snapshot(self, now):
		time_left = ROUND_SECONDS if not self.round_started else max(0, ROUND_SECONDS - int(now - self.round_started))
		if time_left == 0 and not self.winner:
			self.winner = max(self.players, key=lambda pid: self.players[pid]["health"], default=None)
		return {"type": "state", "players": {pid: {k: v for k, v in player.items() if k != "input"}
				for pid, player in self.players.items()}, "bullets": self.bullets,
				"explosions": self.explosions, "time_left": time_left, "winner": self.winner}


if __name__ == "__main__":
	try:
		TankServer().start()
	except KeyboardInterrupt:
		print("\nServer stopped.")
