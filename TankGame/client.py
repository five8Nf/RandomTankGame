"""Pygame client for the two-player networked tank game."""

import json
import math
import random
import socket
import sys
import threading

import pygame

WIDTH, HEIGHT = 1470, 956
PORT = 5555
TANK_SIZE = 42
MAX_HEALTH = 12
WALLS = [(210, 100, 300, 24), (760, 90, 24, 230), (1080, 110, 280, 24),
		 (120, 300, 24, 260), (360, 300, 250, 24), (700, 390, 300, 24),
		 (1160, 330, 24, 260), (180, 650, 280, 24), (540, 610, 24, 210),
		 (790, 700, 300, 24), (1180, 750, 24, 150), (300, 850, 280, 24)]
COLORS = {"1": (177, 198, 139), "2": (190, 111, 86)}
WEAPONS = ("cannon", "machine", "shotgun", "drone", "rocket_launcher", "portal")
WEAPON_LABELS = {"cannon": "CANNON", "machine": "MACHINE GUN", "shotgun": "SHOTGUN", "drone": "DRONE", "rocket_launcher": "ROCKET LAUNCHER", "portal": "PORTAL BULLET"}
WEAPON_COLORS = {"cannon": (224, 177, 91), "machine": (201, 190, 126), "shotgun": (231, 143, 91), "drone": (245, 245, 245), "rocket_launcher": (244, 118, 73), "portal": (114, 201, 214)}


class NetworkClient:
	def __init__(self, host):
		self.socket = socket.create_connection((host, PORT), timeout=5)
		self.socket.settimeout(None)
		self.player_id = None
		self.state = {"players": {}, "bullets": [], "time_left": 180, "winner": None}
		self.lock = threading.Lock()
		self.running = True
		self.send_state = {"turn": 0, "throttle": 0, "strafe": 0, "fire": False, "detonate": False, "weapon": "cannon"}
		threading.Thread(target=self.receive_loop, daemon=True).start()

	def receive_loop(self):
		buffer = ""
		try:
			while self.running:
				data = self.socket.recv(8192)
				if not data:
					break
				buffer += data.decode()
				while "\n" in buffer:
					line, buffer = buffer.split("\n", 1)
					if not line.strip():
						continue
					message = json.loads(line)
					with self.lock:
						if message.get("type") == "welcome":
							self.player_id = message["id"]
						elif message.get("type") == "state":
							self.state = message
		except (ConnectionError, OSError, json.JSONDecodeError):
			pass
		self.running = False

	def send(self, turn, throttle, strafe, fire, weapon, detonate=False, restart=False):
		with self.lock:
			protocol_weapon = "missile" if weapon == "drone" else weapon
			self.send_state = {"turn": turn, "throttle": throttle, "strafe": strafe, "fire": fire,
				"detonate": detonate, "weapon": protocol_weapon, "restart": restart}
			message = (json.dumps(self.send_state) + "\n").encode()
		try:
			self.socket.sendall(message)
		except OSError:
			self.running = False

	def close(self):
		self.running = False
		try:
			self.socket.close()
		except OSError:
			pass


def draw_tank(screen, player_id, player, is_local):
	color = COLORS.get(player_id, (230, 230, 230))
	rect = pygame.Rect(int(player["x"]), int(player["y"]), TANK_SIZE, TANK_SIZE)
	center = rect.center
	angle = player.get("angle", 0)
	direction = (math.cos(angle), math.sin(angle))
	pygame.draw.circle(screen, (41, 48, 37), center, TANK_SIZE // 2)
	pygame.draw.circle(screen, color, center, TANK_SIZE // 2, width=3)
	barrel_start = (center[0] + direction[0] * 1, center[1] + direction[1] * 1)
	barrel_end = (center[0] + direction[0] * 23, center[1] + direction[1] * 23)
	pygame.draw.line(screen, (31, 36, 28), barrel_start, barrel_end, 11)
	pygame.draw.line(screen, color, barrel_start, barrel_end, 8)
	pygame.draw.circle(screen, color, (round(barrel_end[0]), round(barrel_end[1])), 4)
	pygame.draw.circle(screen, (83, 92, 65), center, 7)
	if is_local:
		pygame.draw.circle(screen, (242, 226, 177), center, 4)
	bar = pygame.Rect(rect.x, rect.y - 10, TANK_SIZE, 5)
	pygame.draw.rect(screen, (55, 60, 70), bar)
	pygame.draw.rect(screen, (92, 226, 140),
					(bar.x, bar.y, bar.width * player["health"] / MAX_HEALTH, bar.height))
	if player.get("health", MAX_HEALTH) <= 0:
		elapsed = pygame.time.get_ticks() / 1000
		for smoke_index in range(4):
			smoke_angle = elapsed * (0.8 + smoke_index * 0.15) + smoke_index * 1.7
			smoke_distance = 15 + ((elapsed * 22 + smoke_index * 13) % 34)
			smoke_center = (round(center[0] + math.cos(smoke_angle) * smoke_distance),
				round(center[1] - smoke_distance * 0.8 + math.sin(smoke_angle) * 5))
			smoke_radius = 5 + round((smoke_index + 1) * 1.5)
			pygame.draw.circle(screen, (72, 78, 70), smoke_center, smoke_radius)
			pygame.draw.circle(screen, (108, 108, 92), smoke_center, max(2, smoke_radius - 3))
		for flame_index in range(3):
			flame_x = center[0] - 10 + flame_index * 10
			flame_height = 10 + round(4 * math.sin(elapsed * 8 + flame_index))
			flame_points = [(flame_x - 5, center[1] + 12), (flame_x + 5, center[1] + 12),
				(flame_x, center[1] + 12 + flame_height)]
			pygame.draw.polygon(screen, (239, 105, 47), flame_points)
			pygame.draw.polygon(screen, (255, 214, 89),
				[(flame_x - 2, center[1] + 12), (flame_x + 2, center[1] + 12),
				 (flame_x, center[1] + 9 + flame_height // 2)])


def draw_explosion(screen, explosion):
	progress = 1 - explosion["time_left"] / explosion["duration"]
	center = (round(explosion["x"]), round(explosion["y"]))
	radius = max(24, round(55 + explosion["radius"] * progress * 1.2))
	flash_radius = max(18, round(radius * (1 - progress * 0.45)))
	pygame.draw.circle(screen, (255, 214, 89), center, flash_radius)
	pygame.draw.circle(screen, (255, 245, 187), center, max(5, round(flash_radius * 0.7)))
	pygame.draw.circle(screen, (255, 255, 255), center, max(3, round(flash_radius * 0.35)))
	for ray_direction in range(0, 360, 30):
		radians = math.radians(ray_direction)
		inner = max(4, round(radius * 0.65))
		outer = radius + 28
		pygame.draw.line(screen, (255, 236, 151),
			(center[0] + round(math.cos(radians) * inner), center[1] + round(math.sin(radians) * inner)),
			(center[0] + round(math.cos(radians) * outer), center[1] + round(math.sin(radians) * outer)), 2)


def main():
	host = input("Host IP (press Enter for this computer): ").strip() or "127.0.0.1"
	try:
		client = NetworkClient(host)
	except (OSError, socket.timeout) as error:
		print(f"Could not connect to {host}:{PORT}: {error}")
		sys.exit(1)

	pygame.init()
	screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
	pygame.display.set_caption("Tank Duel")
	clock = pygame.time.Clock()
	world_surface = pygame.Surface((WIDTH, HEIGHT))
	flash_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
	title_font = pygame.font.Font(None, 42)
	info_font = pygame.font.Font(None, 25)
	running = True
	fire_was_down = False
	weapon = "cannon"
	restart_requested = False
	known_drones = {}
	local_explosions = []

	while running and client.running:
		fire = False
		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				running = False
			if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
				fire = True
			if event.type == pygame.KEYDOWN and event.key == pygame.K_m:
				weapon = WEAPONS[(WEAPONS.index(weapon) + 1) % len(WEAPONS)]
			if event.type == pygame.KEYDOWN and event.key == pygame.K_n:
				weapon = WEAPONS[(WEAPONS.index(weapon) - 1) % len(WEAPONS)]
			if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
				restart_requested = True
		keys = pygame.key.get_pressed()
		with client.lock:
			local_player = dict(client.state.get("players", {}).get(client.player_id, {}))
		drone_active = local_player.get("drone_active", local_player.get("missile_active", False))
		turn = int(keys[pygame.K_RIGHT] or keys[pygame.K_d]) - int(keys[pygame.K_LEFT] or keys[pygame.K_a])
		throttle = 0 if drone_active else int(keys[pygame.K_w] or keys[pygame.K_UP]) - int(keys[pygame.K_s] or keys[pygame.K_DOWN])
		strafe = 0 if drone_active else int(keys[pygame.K_e]) - int(keys[pygame.K_q])
		detonate = drone_active and keys[pygame.K_SPACE] and not fire_was_down
		if drone_active:
			fire = False
		elif weapon == "machine":
			fire = keys[pygame.K_SPACE]
		else:
			fire = fire or (keys[pygame.K_SPACE] and not fire_was_down)
		fire_was_down = keys[pygame.K_SPACE]
		client.send(turn, throttle, strafe, fire, weapon, detonate, restart_requested)
		restart_requested = False

		with client.lock:
			state = {"players": dict(client.state["players"]), "bullets": list(client.state["bullets"]),
					 "explosions": list(client.state.get("explosions", [])),
					 "time_left": client.state["time_left"], "winner": client.state["winner"]}
			player_id = client.player_id
		current_drones = {(bullet["owner"], bullet.get("weapon")): bullet
			for bullet in state["bullets"] if bullet.get("weapon") in ("drone", "missile")}
		for drone_key, drone in known_drones.items():
			if drone_key not in current_drones:
				local_explosions.append({"x": drone["x"], "y": drone["y"],
					"radius": 220, "time_left": 0.28, "duration": 0.28})
		known_drones = current_drones
		frame_delta = clock.get_time() / 1000
		for explosion in local_explosions:
			explosion["time_left"] -= frame_delta
		local_explosions = [explosion for explosion in local_explosions
			if explosion["time_left"] > 0]
		all_explosions = state["explosions"] + local_explosions
		shake_strength = max((min(30, round(30 * explosion["time_left"] / explosion["duration"]))
			for explosion in all_explosions), default=0)
		shake_offset = (random.randint(-shake_strength, shake_strength),
			random.randint(-shake_strength, shake_strength))

		screen.fill((38, 57, 42))
		world_surface.fill((38, 57, 42))
		for y in range(0, HEIGHT, 32):
			pygame.draw.line(world_surface, (43, 65, 46), (0, y), (WIDTH, y), 2)
		for x in range(20, WIDTH, 80):
			pygame.draw.circle(world_surface, (52, 75, 49), (x, (x * 7) % HEIGHT), 2)
		for wall in WALLS:
			pygame.draw.rect(world_surface, (83, 74, 57), wall, border_radius=4)
			pygame.draw.rect(world_surface, (178, 145, 91), wall, width=3, border_radius=4)
		for bullet in state["bullets"]:
			if bullet.get("weapon") in ("drone", "missile"):
				center = (int(bullet["x"]), int(bullet["y"]))
				direction = (math.cos(bullet["angle"]), math.sin(bullet["angle"]))
				perpendicular = (-direction[1], direction[0])
				front_left = (center[0] + round(direction[0] * 7 + perpendicular[0] * 7),
					center[1] + round(direction[1] * 7 + perpendicular[1] * 7))
				front_right = (center[0] + round(direction[0] * 7 - perpendicular[0] * 7),
					center[1] + round(direction[1] * 7 - perpendicular[1] * 7))
				back_right = (center[0] - round(direction[0] * 7 + perpendicular[0] * 7),
					center[1] - round(direction[1] * 7 + perpendicular[1] * 7))
				back_left = (center[0] - round(direction[0] * 7 - perpendicular[0] * 7),
					center[1] - round(direction[1] * 7 - perpendicular[1] * 7))
				for rotor in (front_left, front_right, back_right, back_left):
					pygame.draw.line(world_surface, (215, 215, 215), center, rotor, 3)
					pygame.draw.circle(world_surface, (245, 245, 245), rotor, 6, width=2)
				front_left = (center[0] + round(direction[0] * 8 + perpendicular[0] * 5),
					center[1] + round(direction[1] * 8 + perpendicular[1] * 5))
				front_right = (center[0] + round(direction[0] * 8 - perpendicular[0] * 5),
					center[1] + round(direction[1] * 8 - perpendicular[1] * 5))
				back_right = (center[0] - round(direction[0] * 7 + perpendicular[0] * 4),
					center[1] - round(direction[1] * 7 + perpendicular[1] * 4))
				back_left = (center[0] - round(direction[0] * 7 - perpendicular[0] * 4),
					center[1] - round(direction[1] * 7 - perpendicular[1] * 4))
				pygame.draw.polygon(world_surface, (245, 245, 245),
					[front_left, front_right, back_right, back_left])
				pygame.draw.circle(world_surface, (45, 48, 54), center, 5)
				camera = (center[0] + round(direction[0] * 10), center[1] + round(direction[1] * 10))
				pygame.draw.circle(world_surface, (239, 105, 47), camera, 3)
				pygame.draw.line(world_surface, (125, 220, 255), center, camera, 2)
				drone_bar = pygame.Rect(int(bullet["x"]) - 12, int(bullet["y"]) - 18, 24, 3)
				pygame.draw.rect(world_surface, (55, 60, 70), drone_bar)
				pygame.draw.rect(world_surface, (239, 190, 72),
					(drone_bar.x, drone_bar.y, drone_bar.width * bullet["health"] / bullet["max_health"], drone_bar.height))
				drone_battery_bar = pygame.Rect(int(bullet["x"]) - 12, int(bullet["y"]) - 22, 24, 2)
				pygame.draw.rect(world_surface, (55, 60, 70), drone_battery_bar)
				pygame.draw.rect(world_surface, (110, 220, 255),
					(drone_battery_bar.x, drone_battery_bar.y,
					 drone_battery_bar.width * bullet["battery"] / bullet["max_battery"], drone_battery_bar.height))
			elif bullet.get("weapon") == "rocket":
				center = (int(bullet["x"]), int(bullet["y"]))
				direction = (math.cos(bullet["angle"]), math.sin(bullet["angle"]))
				perpendicular = (-direction[1], direction[0])
				body = [(center[0] + round(direction[0] * 9 + perpendicular[0] * 3),
					center[1] + round(direction[1] * 9 + perpendicular[1] * 3)),
					(center[0] + round(direction[0] * 9 - perpendicular[0] * 3),
					center[1] + round(direction[1] * 9 - perpendicular[1] * 3)),
					(center[0] - round(direction[0] * 7 - perpendicular[0] * 3),
					center[1] - round(direction[1] * 7 - perpendicular[1] * 3)),
					(center[0] - round(direction[0] * 7 + perpendicular[0] * 3),
					center[1] - round(direction[1] * 7 + perpendicular[1] * 3))]
				pygame.draw.polygon(world_surface, (244, 118, 73), body)
				pygame.draw.circle(world_surface, (255, 218, 132), center, 2)
			else:
				bullet_color = WEAPON_COLORS.get(bullet.get("weapon", "cannon"), (224, 177, 91))
				pygame.draw.circle(world_surface, bullet_color, (int(bullet["x"]), int(bullet["y"])), bullet.get("radius", 5))
		for other_id, player in state["players"].items():
			draw_tank(world_surface, other_id, player, other_id == player_id)
		for explosion in state["explosions"]:
			draw_explosion(world_surface, explosion)
		for explosion in local_explosions:
			draw_explosion(world_surface, explosion)
		screen.blit(world_surface, shake_offset)
		flash_strength = max((min(210, round(210 * (explosion["time_left"] / explosion["duration"]) ** 2))
			for explosion in all_explosions), default=0)
		if flash_strength:
			flash_surface.fill((255, 255, 255, flash_strength))
			screen.blit(flash_surface, (0, 0))

		header = f"PLAYER {player_id or '-'}    {state['time_left'] // 60:02d}:{state['time_left'] % 60:02d}    DRIVE: W/S    STRAFE: Q/E    TURN: A/D or LEFT/RIGHT"
		screen.blit(info_font.render(header, True, (232, 222, 181)), (20, 18))
		control_text = "A/D: STEER DRONE   SPACE: DETONATE" if drone_active else "SPACE: FIRE"
		loadout = f"M: NEXT   N: PREVIOUS ({WEAPON_LABELS[weapon]})   |   {control_text}   |   R: RESTART"
		screen.blit(info_font.render(loadout, True, WEAPON_COLORS[weapon]), (20, 46))
		if len(state["players"]) < 2:
			message = "Waiting for another player..."
			color = (231, 196, 112)
		elif state["winner"]:
			message = "YOU WIN" if state["winner"] == player_id else "YOU LOSE"
			color = (177, 198, 139) if state["winner"] == player_id else (190, 111, 86)
		else:
			message, color = f"{WEAPON_LABELS[weapon]} - DESTROY THE OTHER TANK", (232, 222, 181)
		screen_rect = screen.get_rect()
		bottom_font = title_font
		while bottom_font.get_height() > screen_rect.height // 14 or bottom_font.size(message)[0] > screen_rect.width - 40:
			font_size = max(20, bottom_font.get_height() - 2)
			bottom_font = pygame.font.Font(None, font_size)
			if font_size == 20:
				break
		label = bottom_font.render(message, True, color)
		label_x = max(20, (screen_rect.width - label.get_width()) // 2)
		label_y = max(20, screen_rect.height - label.get_height() - 24)
		screen.blit(label, (label_x, label_y))
		pygame.display.flip()
		clock.tick(60)

	client.close()
	pygame.quit()


if __name__ == "__main__":
	main()