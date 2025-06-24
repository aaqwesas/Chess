import asyncio
import socketio
import chess
import uvicorn

sio = socketio.AsyncServer(async_mode="asgi", logger=True, cors_allowed_origins="*")
app = socketio.ASGIApp(sio)

waiting = []  # Queue of sids waiting for a game
games = {}  # Mapping: room_id → chess.Board()
replay_requests = {}  # Mapping: room_id → set of sids that requested a replay


@sio.event
async def connect(sid, environ):
    print("connect", sid)


@sio.event
async def join(sid, data):
    """Client says “I want a game”."""
    waiting.append(sid)
    # If there's already someone waiting, pair them.
    if len(waiting) >= 2:
        p1, p2 = waiting.pop(0), waiting.pop(0)
        room = f"room_{p1}_{p2}"
        board = chess.Board()
        games[room] = board

        # Save each player's session info with room and color
        await sio.save_session(p1, {"room": room, "color": "white"})
        await sio.save_session(p2, {"room": room, "color": "black"})
        await sio.enter_room(p1, room)
        await sio.enter_room(p2, room)

        # Send "start" message with the initial FEN and assigned colors
        await sio.emit(
            "start", {"fen": board.fen(), "your_color": "white"}, room=room, to=p1
        )
        await sio.emit(
            "start", {"fen": board.fen(), "your_color": "black"}, room=room, to=p2
        )


@sio.event
async def move(sid, data):
    """Data format: { from: "e2", to: "e4", promotion: "q" }."""
    session = await sio.get_session(sid)
    room = session["room"]
    board = games.get(room)
    if board is None:
        return

    # Build a UCI move string
    uci = data["from"] + data["to"]
    if "promotion" in data:
        uci += data["promotion"]
    move = chess.Move.from_uci(uci)

    # Validate & apply the move
    if move in board.legal_moves:
        board.push(move)
        # Broadcast the move (and new FEN) to both players.
        await sio.emit("move", {"uci": uci, "fen": board.fen()}, room=room)
        # Check for game end.
        if board.is_game_over():
            result = board.result()
            await sio.emit("game_over", {"result": result}, room=room)
    else:
        # Notify the client that the move was invalid.
        await sio.emit("invalid", {"uci": uci}, to=sid)


@sio.event
async def replay(sid, data):
    """
    Handles a client's request to replay the game.
    When both players in a room request a replay, the game restarts.
    """
    session = await sio.get_session(sid)
    room = session.get("room")
    if not room:
        return

    # Record the replay request from this client.
    if room not in replay_requests:
        replay_requests[room] = set()
    replay_requests[room].add(sid)
    print(f"Replay requested from {sid} in room {room}.")

    # If both players have requested a replay, restart the game.
    if len(replay_requests[room]) == 2:
        new_board = chess.Board()
        games[room] = new_board
        await sio.emit("replay_start", {"fen": new_board.fen()}, room=room)
        print(f"Game in room {room} restarted.")
        del replay_requests[room]


@sio.event
async def quit(sid, data):
    session = await sio.get_session(sid)
    room = session.get("room")
    if not room:
        return

    # Determine the opponent's sid based on the room name (format: room_s1_s2).
    parts = room.split("_")
    if len(parts) < 3:
        return
    s1, s2 = parts[1], parts[2]
    opponent = s2 if sid == s1 else s1

    # Inform both clients that the opponent left.
    await sio.emit("opponent_left", room=room)
    print(f"{sid} quit the game in room {room}. Opponent {opponent} will be re-queued.")

    # Remove the game and any pending replay requests.
    if room in games:
        del games[room]
    if room in replay_requests:
        del replay_requests[room]

    # Remove the room attribute from the opponent's session and add them to the waiting queue.
    opp_session = await sio.get_session(opponent)
    if "room" in opp_session:
        del opp_session["room"]
    if opponent not in waiting:
        waiting.append(opponent)

    # Remove the quitting client's association with the room.
    await sio.leave_room(sid, room)


@sio.event
async def disconnect(sid):
    # Clean up waiting queue and any active game where the sid is involved.
    print("disconnect", sid)
    if sid in waiting:
        waiting.remove(sid)
    # If sid is part of an ongoing game, notify the opponent and remove the game.
    for room, board in list(games.items()):
        s1, s2 = room.split("_")[1:]
        if sid in (s1, s2):
            opponent = s2 if sid == s1 else s1
            await sio.emit("opponent_left", room=room)
            del games[room]
            if room in replay_requests:
                del replay_requests[room]
            break


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
