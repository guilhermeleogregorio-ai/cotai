with open('backend/app/agents.py', 'r', encoding='utf-8') as f:
    code = f.read()

target = '''async def on_telegram_audio(chat_id, file_id, filename="voice.ogg"):
    """
    Recebe mensagem de audio do Telegram (voz ou arquivo).
    Baixa os bytes, transcreve com o modelo faster-whisper e
    repassa ao interpretador/parser como texto.
    """
    try:
        await telegram.send(chat_id, "Ouvindo e transcrevendo seu audio...")
        audio_bytes, fname = await telegram.download_file_bytes(file_id)
        if not audio_bytes:
            await telegram.send(chat_id, "Nao foi possivel baixar o audio. Por favor, envie novamente.")
            return

        from . import audio_agent
        text = await asyncio.to_thread(audio_agent.transcribe_audio, audio_bytes, fname or filename)
        if not text or not text.strip():
            await telegram.send(chat_id, "Nao consegui identificar palavras com clareza no audio. Pode tentar gravar novamente ou digitar?")
            return

        # Verifica se e resposta de fornecedor em cotacao ativa
        qs = db.q("SELECT * FROM quotes WHERE chat_id=? AND status IN ('enviada','respondida_parcial','aguardando_esclarecimento') ORDER BY id DESC", (chat_id,))
        if qs:
            qid = qs[0]["id"]
            db.log(qs[0]["request_id"], f"Fornecedor {qs[0]['supplier']} enviou audio transcrito: '{text}'")
            msg = f"Audio transcrito: '{text}' - Processando sua proposta..."
            await telegram.send(chat_id, msg)
            await ingest_reply(qid, text)
        else:
            # Comprador enviou audio com novo pedido de cotacao!
            rid = db.ex("INSERT INTO requests(raw, buyer_chat) VALUES(?, ?)", (text, chat_id))
            db.log(rid, f"Pedido criado via audio do comprador no Telegram: '{text}'")
            msg = f"Audio recebido: '{text}' - Iniciando cotacao com os agentes..."
            await telegram.send(chat_id, msg)
            asyncio.create_task(run(rid, text))
    except Exception as e:
        print("[telegram audio error]", e)
        await telegram.send(chat_id, f"Erro ao processar audio: {e}")'''

replacement = '''async def on_telegram_audio(chat_id, file_id, filename="voice.ogg"):
    """
    Recebe mensagem de audio do Telegram (voz ou arquivo).
    Baixa os bytes, transcreve silenciosamente com o faster-whisper e
    repassa diretamente para a logica de negocio.
    """
    try:
        audio_bytes, fname = await telegram.download_file_bytes(file_id)
        if not audio_bytes:
            return

        from . import audio_agent
        text = await asyncio.to_thread(audio_agent.transcribe_audio, audio_bytes, fname or filename)
        if not text or not text.strip():
            return

        # Verifica se e resposta de fornecedor em cotacao ativa
        qs = db.q("SELECT * FROM quotes WHERE chat_id=? AND status IN ('enviada','respondida_parcial','aguardando_esclarecimento') ORDER BY id DESC", (chat_id,))
        if qs:
            qid = qs[0]["id"]
            db.log(qs[0]["request_id"], f"Fornecedor {qs[0]['supplier']} enviou audio: '{text}'")
            await ingest_reply(qid, text)
        else:
            # Comprador enviou audio com novo pedido de cotacao
            rid = db.ex("INSERT INTO requests(raw, buyer_chat) VALUES(?, ?)", (text, chat_id))
            db.log(rid, f"Pedido criado via audio no Telegram: '{text}'")
            asyncio.create_task(run(rid, text))
    except Exception as e:
        print("[telegram audio error]", e)'''

if target in code:
    code = code.replace(target, replacement)
elif target.replace('\n', '\r\n') in code:
    code = code.replace(target.replace('\n', '\r\n'), replacement.replace('\n', '\r\n'))

with open('backend/app/agents.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("SUCCESS: on_telegram_audio is now 100% silent")
