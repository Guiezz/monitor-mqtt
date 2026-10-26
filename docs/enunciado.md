# Projeto MQTT (3 pontos) — Enunciado

Imagine um cenário em que um ambiente industrial (e.g., uma caldeira) é monitorado por um conjunto de sensores de temperatura que envia dados a cada 60 segundos para um broker MQTT. Ligado ao broker existem dois outros sistemas: o serviço Compute Average Temperature (CAT), que calcula a média das temperaturas monitoradas, e o serviço Alarms, que dispara mensagens de vários tipos de alarmes (fogo, temperatura alta, vazamento de água) para operadores humanos do sistema.

O serviço CAT funciona como uma calculadora remota medindo a média dos valores de temperatura enviados nos últimos 120 segundos. Ele deve ser criado como um serviço que escuta (está inscrito para ouvir) tópicos de publicação de temperatura e executa a operação da média a partir do payload enviado no tópico. Esse serviço pode publicar duas mensagens:
- aumento de temperatura repentina, se as duas últimas médias diferem em 5 graus;
- temperatura alta, se a média indicar valor acima de 200 graus.

O serviço Alarms basicamente monitora esses dois eventos e publica um alarme na interface gráfica do sistema de monitoramento quando eles ocorrem.

A atividade MQTT é portanto implementar sensores simulados (o número de sensores pode aumentar ou diminuir) e os serviços CAT e Alarms (1,5 pontos). Este último pode ser apenas um sistema que imprime mensagens no console ou pode ter uma interface gráfica (0,5 pontos adicionais).

SUGESTÃO: usar o MQTT Paho com o Mosquitto e criar 3 projetos distintos (um para o sensor e os outros dois para os serviços). Podem-se escolher outras plataformas e linguagens desde que usem um MQTT "raiz".

Entrega: colocar no GitHub do projeto um pequeno vídeo mostrando a execução, na própria máquina, dos sensores simulados enviando dados, do serviço CAT computando as médias e do serviço Alarms disparando pelo menos um dos alarmes (1 ponto).
