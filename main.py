from api import call_chat

message = "Un escargot grimpe un mur de 10 mètres. Le jour il monte de 3 mètres, la nuit il glisse de 2 mètres. En combien de jours atteint-il le sommet ? Explique ton raisonnement."

response = call_chat(message)

print("response : ", response)
