from PIL import Image, ImageDraw, ImageFont

# Cria placeholder do brasao TJBA
img = Image.new('RGBA', (300, 300), (255, 255, 255, 0))
draw = ImageDraw.Draw(img)

# Circulos concentricos
draw.ellipse([20, 20, 280, 280], outline='#1e3a5f', width=10)
draw.ellipse([50, 50, 250, 250], outline='#2563eb', width=5)
draw.ellipse([80, 80, 220, 220], outline='#3b82f6', width=3)

# Texto central
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    font2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
except:
    font = ImageFont.load_default()
    font2 = font

draw.text((90, 120), "TJBA", fill='#1e3a5f', font=font)
draw.text((50, 170), "Justica", fill='#6b7280', font=font2)
draw.text((60, 195), "Eleitoral", fill='#6b7280', font=font2)

# Estrelas nos cantos
for pos in [(40, 40), (250, 40), (40, 250), (250, 250)]:
    x, y = pos
    draw.polygon([(x, y-8), (x+6, y+6), (x-8, y+2), (x+8, y+2), (x-6, y+6)], fill='#f59e0b')

img.save('/home/ivan/PythonProjects/send_of_v4/assets/tjba.png')
print('Placeholder criado em assets/tjba.png')
