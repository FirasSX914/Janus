# Demo janus : les deux verdicts a la suite. AUCUN appel API.
#
# `--replay` rejoue les JSONL commites : les fournisseurs qu'il installe levent
# une exception si on les appelle, donc le run n'aboutit que parce que les 500
# lignes sont deja la, et il echoue bruyamment sinon. `--task` designe les deux
# mesures commitees dans le depot. La commande affichee est la vraie, lancable
# telle quelle depuis un clone.
#
#   vhs experiments/janus_demo.tape
#
# Necessite vhs, ttyd et ffmpeg.

Output results/figures/janus_demo.gif
# VHS 0.12.0 sous Windows capture les frames mais n'appelle jamais ffmpeg :
# verifie avec un shim qui journalise les appels, le journal reste vide. On lui
# fait donc ecrire aussi les frames, et on encode derriere :
#
#   ffmpeg -y -framerate 20 -i .vhs-frames/frame-text-%05d.png #     -filter_complex "[0:v]crop=1023:1030:0:0,split[a][b];#        [a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3" #     results/figures/janus_demo.gif
#
# Le crop retire l'espace mort sous la sortie la plus courte des deux.
#
# Sur une machine ou VHS emet le GIF lui-meme, la premiere ligne suffit.
Output .vhs-frames/

Require python

Set Shell powershell
Set FontFamily "Consolas"
Set FontSize 20
Set Width 1100
Set Height 1180
Set Padding 24
Set Framerate 20
Set TypingSpeed 28ms
Set Theme { "name": "janus", "background": "#12161c", "foreground": "#d5dae1", "cursor": "#7aa2f7", "selection": "#2a3040", "black": "#12161c", "red": "#f7768e", "green": "#9ece6a", "yellow": "#e0af68", "blue": "#7aa2f7", "magenta": "#bb9af7", "cyan": "#7dcfff", "white": "#d5dae1", "brightBlack": "#7f8a99", "brightRed": "#f7768e", "brightGreen": "#9ece6a", "brightYellow": "#e0af68", "brightBlue": "#7aa2f7", "brightMagenta": "#bb9af7", "brightCyan": "#7dcfff", "brightWhite": "#ffffff" }

# Mise en place hors champ : on ne filme pas un cd ni un clear.
Hide
Type "Set-Location 'C:\Users\ayadi\Documents\Projects\Calibre'" Enter
# Prompt reduit a "$ " : le chemin complet mangerait un quart de la largeur.
Type "function prompt { '$ ' }" Enter
Type "clear" Enter
Sleep 2s
Show

# ---------------------------------------------------------------- Banking77
Type "janus --color always measure --replay --task banking77 --top 1"
Sleep 400ms
Enter
Sleep 800ms
# Laisser lire le verdict : c'est la moitie du propos.
Sleep 5s

Hide
Type "clear" Enter
Sleep 400ms
Show

# --------------------------------------------------------- Web of Science
Type "janus --color always measure --replay --task wos --top 1"
Sleep 400ms
Enter
Sleep 800ms
# Derniere image : DO NOT ROUTE. C'est le point de la demo, on s'y arrete.
Sleep 7s
