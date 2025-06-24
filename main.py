import pygame
import sys
import socketio
import chess
import asyncio

# ─── Networking setup ───────────────────────────
# Use the asynchronous client from socketio
sio = socketio.AsyncClient()

# Global game state variables
board = chess.Board()
my_color = None

game_over_display = False
game_over_message = ""
replay_chosen = False
waiting_for_opponent = False
sel_sq = None


@sio.event
async def connect():
    print("Connected, asking to join")
    await sio.emit("join", {})


@sio.on("start")
async def on_start(data):
    global \
        board, \
        my_color, \
        game_over_display, \
        replay_chosen, \
        waiting_for_opponent, \
        sel_sq
    board = chess.Board(data["fen"])
    my_color = data["your_color"]
    game_over_display = False
    replay_chosen = False
    waiting_for_opponent = False
    sel_sq = None
    print("Game start! You are", my_color)


@sio.on("move")
async def on_move(data):
    global board
    board.set_fen(data["fen"])


@sio.on("invalid")
async def on_invalid(data):
    print("Invalid move:", data["uci"])


@sio.on("game_over")
async def on_game_over(data):
    global game_over_display, game_over_message
    game_over_display = True
    game_over_message = "Game over: " + data["result"]
    print(game_over_message)


@sio.on("replay_start")
async def on_replay_start(data):
    global board, game_over_display, sel_sq, replay_chosen, waiting_for_opponent
    board = chess.Board(data["fen"])
    game_over_display = False
    sel_sq = None
    replay_chosen = False
    waiting_for_opponent = False
    print("Game restarted!")


@sio.on("opponent_left")
async def on_leave():
    print("Opponent left. Rejoining waiting queue...")
    await sio.emit("join", {})


@sio.event
async def disconnect():
    print("Disconnected")
    # Post a QUIT event to ensure the pygame loop exits.
    pygame.event.post(pygame.event.Event(pygame.QUIT))


# ─── Pygame setup ──────────────────────────────
pygame.init()
size = 800
screen = pygame.display.set_mode((size, size))
clock = pygame.time.Clock()

# Set up a font for drawing text.
font = pygame.font.Font(None, 36)

# Load images for the chess pieces.
images = {}
for piece in ["P", "N", "B", "R", "Q", "K", "p", "n", "b", "r", "q", "k"]:
    images[piece] = pygame.transform.scale(
        pygame.image.load(f"images/{piece}.png"), (size // 8, size // 8)
    )

CELL = size // 8
LIGHT = pygame.Color("#F0D9B5")
DARK = pygame.Color("#B58863")


def get_square_from_mouse(pos):
    """Maps mouse coordinates to a chess square (file, rank) based on board orientation."""
    x, y = pos
    j = x // CELL  # column on screen
    i = y // CELL  # row on screen
    if my_color == "black":
        file = 7 - j
        rank = i
    else:
        file = j
        rank = 7 - i
    return chess.square(file, rank)


def draw_board():
    # Draw each square and then any piece on that square.
    for i in range(8):
        for j in range(8):
            if my_color == "black":
                board_file = 7 - j
                board_rank = i
            else:
                board_file = j
                board_rank = 7 - i

            rect = pygame.Rect(j * CELL, i * CELL, CELL, CELL)
            square_color = LIGHT if ((board_file + board_rank) % 2 == 0) else DARK
            pygame.draw.rect(screen, square_color, rect)
            piece = board.piece_at(chess.square(board_file, board_rank))
            if piece:
                img = images[piece.symbol()]
                screen.blit(img, rect.topleft)

    if sel_sq is not None:
        file = chess.square_file(sel_sq)
        rank = chess.square_rank(sel_sq)
        if my_color == "black":
            j = 7 - file
            i = rank
        else:
            j = file
            i = 7 - rank
        highlight_rect = pygame.Rect(j * CELL, i * CELL, CELL, CELL)
        pygame.draw.rect(screen, pygame.Color("yellow"), highlight_rect, 3)


def draw_turn_indicator():
    turn_text = "White's turn" if board.turn else "Black's turn"
    text_surface = font.render(turn_text, True, pygame.Color("white"))
    screen.blit(text_surface, (10, 10))


def draw_game_over_overlay():
    """Draw the overlay displaying the game over message and Replay/Quit buttons."""
    overlay = pygame.Surface((size, size))
    overlay.set_alpha(200)
    overlay.fill((0, 0, 0))
    screen.blit(overlay, (0, 0))

    message_surface = font.render(game_over_message, True, pygame.Color("white"))
    message_rect = message_surface.get_rect(center=(size // 2, size // 2 - 40))
    screen.blit(message_surface, message_rect)

    replay_button_rect = pygame.Rect(size // 2 - 100, size // 2 + 20, 80, 40)
    quit_button_rect = pygame.Rect(size // 2 + 20, size // 2 + 20, 80, 40)

    pygame.draw.rect(screen, pygame.Color("green"), replay_button_rect)
    pygame.draw.rect(screen, pygame.Color("red"), quit_button_rect)

    replay_text = font.render("Replay", True, pygame.Color("white"))
    quit_text = font.render("Quit", True, pygame.Color("white"))
    screen.blit(replay_text, replay_text.get_rect(center=replay_button_rect.center))
    screen.blit(quit_text, quit_text.get_rect(center=quit_button_rect.center))

    return replay_button_rect, quit_button_rect


async def game_loop():
    global sel_sq, replay_chosen, waiting_for_opponent
    while True:
        if game_over_display:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    await sio.disconnect()
                    pygame.quit()
                    sys.exit()
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    pos = ev.pos
                    replay_button_rect, quit_button_rect = draw_game_over_overlay()
                    if replay_button_rect.collidepoint(pos):
                        if not replay_chosen:
                            replay_chosen = True
                            await sio.emit("replay", {})
                            waiting_for_opponent = True
                            print("Replay requested. Waiting for opponent...")
                    elif quit_button_rect.collidepoint(pos):
                        await sio.emit("quit", {})
                        await sio.disconnect()
                        pygame.quit()
                        sys.exit()
            screen.fill((0, 0, 0))
            draw_board()
            draw_turn_indicator()
            draw_game_over_overlay()
            pygame.display.flip()
            await asyncio.sleep(1 / 30)
            continue

        # Normal gameplay event processing.
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                await sio.disconnect()
                pygame.quit()
                sys.exit()
            elif ev.type == pygame.MOUSEBUTTONDOWN and my_color:
                sq = get_square_from_mouse(ev.pos)
                if sel_sq is None:
                    # Pick up the piece if it belongs to the player.
                    if board.piece_at(sq) and board.color_at(sq) == (
                        my_color == "white"
                    ):
                        sel_sq = sq
                else:
                    if board.piece_at(sq) and board.color_at(sq) == (
                        my_color == "white"
                    ):
                        sel_sq = sq
                    else:
                        piece = board.piece_at(sel_sq)
                        if piece and piece.symbol().lower() == "p":
                            promotion_rank = 7 if my_color == "white" else 0
                            if chess.square_rank(sq) == promotion_rank:
                                move_obj = chess.Move(sel_sq, sq, promotion=chess.QUEEN)
                            else:
                                move_obj = chess.Move(sel_sq, sq)
                        else:
                            move_obj = chess.Move(sel_sq, sq)
                        if move_obj in board.legal_moves:
                            uci = move_obj.uci()
                            payload = {"from": uci[0:2], "to": uci[2:4]}
                            if len(uci) == 5:
                                payload["promotion"] = uci[4]
                            print("→ emitting move:", payload)
                            await sio.emit("move", payload)
                        sel_sq = None

        screen.fill((0, 0, 0))
        draw_board()
        draw_turn_indicator()
        pygame.display.flip()
        await asyncio.sleep(0)  # roughly 30 FPS


async def main():
    await sio.connect("http://localhost:8000")
    await asyncio.gather(game_loop(), sio.wait())


if __name__ == "__main__":
    asyncio.run(main())
