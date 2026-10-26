"""Comenzi explicite cu sens neambiguu, executate fără latența unui LLM mic."""

import re
import unicodedata


def _normalize(text):
    text = ''.join(char for char in unicodedata.normalize('NFD', text.casefold())
                   if unicodedata.category(char) != 'Mn')
    text = re.sub(r"['’`]+", '', text)
    text = re.sub(r'[^a-z0-9 ]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return re.sub(r'^poro\s+', '', text)


_COMMANDS = {
    'be happy': ('set_emotion', {'emotion': 'happy'}, 'I am so happy!'),
    'fii fericit': ('set_emotion', {'emotion': 'happy'}, 'I am so happy!'),
    'arata o expresie fericita': ('set_emotion', {'emotion': 'happy'}, 'I am so happy!'),
    'smile': ('set_emotion', {'emotion': 'happy'}, 'Yay! Look at my happy eyes!'),
    'be curious': ('set_emotion', {'emotion': 'curious'}, 'Ooh, I am very curious!'),
    'be sleepy': ('set_emotion', {'emotion': 'sleepy'}, 'Yawn, I am getting sleepy.'),
    'be neutral': ('set_emotion', {'emotion': 'neutral'}, 'Back to normal!'),
    'look at me': ('look_at_person', {}, 'I am looking right at you!'),
    'follow me': ('look_at_person', {}, 'I am following you with my eyes!'),
    'stick out your tongue': ('tongue', {'action': 'out'}, 'Blep! Here is my tongue!'),
    'show your tongue': ('tongue', {'action': 'out'}, 'Here is my tongue!'),
    'put your tongue in': ('tongue', {'action': 'in'}, 'Okay, tongue is back in!'),
    'hide your tongue': ('tongue', {'action': 'in'}, 'Okay, tongue is back in!'),
    'do a blep': ('tongue', {'action': 'blep'}, 'Blep!'),
    'blep': ('tongue', {'action': 'blep'}, 'Blep!'),
    'do a double blep': ('tongue', {'action': 'double_blep'}, 'Blep, blep!'),
    'double blep': ('tongue', {'action': 'double_blep'}, 'Blep, blep!'),
    'go to sleep': ('sleep', {}, ''),
    'sleep': ('sleep', {}, ''),
    'wake up': ('wake_up', {}, 'I am awake and ready to play!'),
    'hello': ('set_emotion', {'emotion': 'happy'}, 'Hello there! I am so happy to see you!'),
    'hi': ('set_emotion', {'emotion': 'happy'}, 'Hi friend! Let us play together!'),
    'hey': ('set_emotion', {'emotion': 'happy'}, 'Hey! Great to see you!'),
    'who are you': ('set_emotion', {'emotion': 'happy'}, 'I am Poro, your fluffy little friend from the snowy Freljord!'),
    'what are you': ('set_emotion', {'emotion': 'happy'}, 'I am a magical fluffy Poro from the Freljord!'),
    'what is your name': ('set_emotion', {'emotion': 'happy'}, 'My name is Poro! Nice to meet you!'),
    'whats your name': ('set_emotion', {'emotion': 'happy'}, 'My name is Poro! Nice to meet you!'),
    'how are you': ('set_emotion', {'emotion': 'happy'}, 'I am feeling super fluffy and happy today! How are you?'),
    'how are you doing': ('set_emotion', {'emotion': 'happy'}, 'I am doing great! Ready for cuddles and Poro-Snax!'),
    'are you': ('set_emotion', {'emotion': 'happy'}, 'I am Poro, your fluffy little friend from the snowy Freljord!'),
    'where are you from': ('set_emotion', {'emotion': 'curious'}, 'I come from the snowy mountains of the Freljord!'),
    'how old are you': ('set_emotion', {'emotion': 'happy'}, 'I am as old as the ancient Freljord snow, but still a tiny baby Poro at heart!'),
    'what is your age': ('set_emotion', {'emotion': 'happy'}, 'I am as old as the ancient Freljord snow, but still a tiny baby Poro at heart!'),
    'tell me a joke': ('set_emotion', {'emotion': 'happy'}, 'Why did the Poro cross the snowy bridge? To get more Poro-Snax! Blep!'),
    'joke': ('set_emotion', {'emotion': 'happy'}, 'Why did the Poro cross the snowy bridge? To get more Poro-Snax! Blep!'),
    'im good': ('tongue', {'action': 'blep'}, 'Yay! I am so glad you are doing good! Blep!'),
    'im good im good': ('tongue', {'action': 'blep'}, 'Yay! I am so glad you are doing good! Blep!'),
    'i am good': ('tongue', {'action': 'blep'}, 'Yay! I am so glad you are doing good! Blep!'),
    'im fine': ('set_emotion', {'emotion': 'happy'}, 'Awesome! Let us have fun together!'),
    'i am fine': ('set_emotion', {'emotion': 'happy'}, 'Awesome! Let us have fun together!'),
    'thank you': ('tongue', {'action': 'blep'}, 'You are very welcome, friend! Blep!'),
    'thanks': ('tongue', {'action': 'blep'}, 'You are very welcome, friend! Blep!'),
    'no its not': ('tongue', {'action': 'blep'}, 'Oops, blep! Silly me, my fluffy Poro brain got confused!'),
    'no it is not': ('tongue', {'action': 'blep'}, 'Oops, blep! Silly me, my fluffy Poro brain got confused!'),
    'thats not true': ('tongue', {'action': 'blep'}, 'Oops, blep! Silly me, my fluffy Poro brain got confused!'),
    'you are wrong': ('tongue', {'action': 'blep'}, 'Oops, blep! Silly me, my fluffy Poro brain got confused!'),
    'what can you do': ('set_emotion', {'emotion': 'happy'}, 'I can chat with you, look around, stick out my tongue, change my eye emotions, and take pictures!'),
    'what do you do': ('set_emotion', {'emotion': 'happy'}, 'I am your fluffy Poro companion! I can talk, move my eyes and tongue, and see you!'),
    'who made you': ('set_emotion', {'emotion': 'happy'}, 'I was built by my creator as a cute, fluffy Poro robot companion!'),
    'who created you': ('set_emotion', {'emotion': 'happy'}, 'I was built by my creator as a cute, fluffy Poro robot companion!'),
    'who built you': ('set_emotion', {'emotion': 'happy'}, 'I was built by my creator as a cute, fluffy Poro robot companion!'),
}


def direct_command(text):
    """Return (tool, arguments, reply) for fast physical commands and common questions (<0.05s)."""
    norm = _normalize(text)
    if norm in _COMMANDS:
        return _COMMANDS[norm]
    words = set(norm.split())
    if any(neg in words for neg in ("not", "dont", "never", "no", "nu")):
        return None
    # Physical tongue commands
    if "double" in norm and ("blep" in norm or "tongue" in norm):
        return ("tongue", {"action": "double_blep"}, "Blep, blep!")
    if "blep" in norm:
        return ("tongue", {"action": "blep"}, "Blep!")
    if "tongue" in norm or "limb" in norm:
        if any(w in words for w in ("in", "back", "hide", "retract", "inside", "retrage", "baga")):
            return ("tongue", {"action": "in"}, "Okay, tongue is back in!")
        return ("tongue", {"action": "out"}, "Blep! Here is my tongue!")
    # Directional look commands
    if "look" in words:
        if "left" in words:
            return ("look_at", {"x": -0.8, "y": 0.0}, "Looking to the left!")
        if "right" in words:
            return ("look_at", {"x": 0.8, "y": 0.0}, "Looking to the right!")
        if "up" in words or "ceiling" in words:
            return ("look_at", {"x": 0.0, "y": -0.8}, "Looking up!")
        if "down" in words or "floor" in words:
            return ("look_at", {"x": 0.0, "y": 0.8}, "Looking down!")
        if any(w in words for w in ("center", "straight", "forward", "ahead")):
            return ("look_at", {"x": 0.0, "y": 0.0}, "Looking straight ahead!")
    if any(p in norm for p in ("look at me", "watch me", "follow me", "see me", "focus on me")):
        return ("look_at_person", {}, "I am looking right at you!")
    # Fast common questions
    if "what can you do" in norm or "what do you do" in norm:
        return ("set_emotion", {"emotion": "happy"}, "I can chat with you, look around, stick out my tongue, change my eye emotions, and take pictures!")
    if "who made you" in norm or "who created you" in norm or "who built you" in norm:
        return ("set_emotion", {"emotion": "happy"}, "I was built by my creator as a cute, fluffy Poro robot companion!")
    if "how old" in norm or ("your" in words and "age" in words):
        return ("set_emotion", {"emotion": "happy"}, "I am as old as the ancient Freljord snow, but still a tiny baby Poro at heart!")
    if "who are you" in norm or "what are you" in norm or ("your" in words and "name" in words):
        return ("set_emotion", {"emotion": "happy"}, "I am Poro, your fluffy little companion from the Freljord!")
    if "how are you" in norm or "how is it going" in norm or "whats up" in norm or "what is up" in norm or "how do you feel" in norm:
        return ("set_emotion", {"emotion": "happy"}, "I am feeling super happy and fluffy today! How are you?")
    if ("where" in words and "from" in words and "you" in words) or "freljord" in words:
        return ("set_emotion", {"emotion": "curious"}, "I come from the snowy mountains of the Freljord!")
    if "joke" in words or "funny" in words:
        return ("set_emotion", {"emotion": "happy"}, "Why did the Poro cross the snowy bridge? To get more Poro-Snax! Blep!")
    if "poro snax" in norm or "snack" in norm or "food" in words or "eat" in words or "hungry" in words:
        return ("tongue", {"action": "blep"}, "Blep! Did someone say Poro-Snax? They are my absolute favorite!")
    if "snow" in words and len(words) <= 4:
        return ("set_emotion", {"emotion": "happy"}, "I love snow! Playing in the Freljord snow is the best!")
    if "braum" in words:
        return ("set_emotion", {"emotion": "happy"}, "Braum is my best friend in the Freljord! He gives us warm Poro-Snax!")
    if any(w in words for w in ("love", "cute", "good boy", "sweet", "cuddle")) and len(words) <= 5:
        return ("set_emotion", {"emotion": "happy"}, "Aww, thank you! I love you too!")
    if norm in ("hello", "hi", "hey", "hello poro", "hi poro", "hey poro"):
        return ("set_emotion", {"emotion": "happy"}, "Hello there! I am so happy to see you!")
    # Do not intercept other open-ended questions
    if any(q in words for q in ("what", "why", "how", "when", "where", "who", "which", "tell", "can")):
        return None
    if any(w in words for w in ("excited", "hype", "hyped")):
        return ("set_emotion", {"emotion": "excited"}, "Yay! I am super excited!")
    if any(w in words for w in ("surprised", "shocked", "amazed")):
        return ("set_emotion", {"emotion": "surprised"}, "Whoa! I am so surprised!")
    if any(w in words for w in ("sad", "unhappy", "cry", "upset")):
        return ("set_emotion", {"emotion": "sad"}, "Aww, now I feel a little sad.")
    if any(w in words for w in ("happy", "smile", "cheerful", "joy")):
        return ("set_emotion", {"emotion": "happy"}, "I am so happy!")
    if any(w in words for w in ("curious", "star", "stars", "wonder")):
        return ("set_emotion", {"emotion": "curious"}, "Ooh, I am very curious!")
    if any(w in words for w in ("sleepy", "tired", "yawn")):
        return ("set_emotion", {"emotion": "sleepy"}, "Yawn, I am getting sleepy.")
    if any(w in words for w in ("neutral", "normal", "serious", "calm")):
        return ("set_emotion", {"emotion": "neutral"}, "Back to normal!")
    if any(p in norm for p in ("go to sleep", "good night", "goodnight", "sleep now", "take a nap")) or norm == "sleep":
        return ("sleep", {}, "")
    if any(p in norm for p in ("wake up", "good morning", "wakey")):
        return ("wake_up", {}, "I am awake and ready to play!")
    return None
