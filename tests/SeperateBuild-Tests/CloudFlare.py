import requests

ACCOUNT_ID = "00ed78486159dbce2f059215aeee83e9"
API_KEY = "cfut_Xj8Vho3uLNSgFu8YK0TewCHDweD5Kxb1PXDjhmYY84a97359"
drill="Begin the drill by standing at the side of the pool with your feet shoulder-width apart. Starting with your hands in a neutral position, take 10 seconds to flutter your hands across the top of the water, focusing on quick and light movements. Next, for 10 seconds, hold an arm in a front pull position and do 6-8 small hand circles, first clockwise and then counterclockwise, keeping your elbow firm and your arm straight. Rapidly extend the arm back to the neutral position, and then repeat with the opposite arm. Continue alternating arms and repeating hand circles for 10 seconds. Finally, sprint across the pool, using the freestyle strokes to propel yourself through the water, focusing on quick and powerful movements, alternating arms and maintaining a steady pace for 20 seconds. Rest for 10 seconds, and then repeat the entire sequence for a total of 5 rounds."
url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/meta/llama-3.1-8b-instruct"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

data = {
    "messages": [
    {"role": "user", "content":f'turn this drill ({drill}) into as many pose instruction sets as needed formatted as such: ("hipx":0,"hipy":0,"hipz":0,"lefthipx":90,"lefthipy":0,"lefthipz":0,"righthipx":0,"righthipy":0,"righthipz":0,"leftkneex":0,"leftkneey":0,"leftkneez":0,"rightkneex":0,"rightkneey":0,"rightkneez":0,"spinex":0,"spiney":0,"spinez":0,"neckx":0,"necky":0,"neckz":0,"leftshoulderx":0,"leftshouldery":0,"leftshoulderz":0,"rightshoulderx":0,"rightshouldery":0,"rightshoulderz":0,"leftelbowx":0,"leftelbowy":0,"leftelbowz":0,"rightelbowx":0,"rightelbowy":0,"rightelbowz":0,"positionx":0,"positiony":0,"positionz":0) the steps need to be formatted as json arrays with the same stucture just provided each value does exactly as it says meaning for example lefthipx=90 means that the person would be kicking the their left leg forward lefthipy=90 by istself woudnt do much besides turning the leg in the waty that the entire leg stays the same but the foot is pointing 90 dgreed to the side but a change of 90 in both x and y would be the same s just making the left hipz 90 so you get it, now changing the hipy sould make it so that the upper body stays straight but the lower body rotates, spiney would do tyhe opposite; upper body changes lower body dosent, position moves everything, body parts are relativley binded meaning leftkneex=leftkneex+lefthipx, so you dont have to worry about that part. Every value is rotation based, do not be afraid to change a lot of values per each move and each of the steps should represent a positio in the drill for example high knees miht only require 2 positions one with the lefthipx=90,leftkneex=-90 and one with the righthipx=90,rightkneex=-90 but mabye a drill like burpees may need a lot more.'},
    {"role":"system", "content":'You are a human with good spatial reasoning and understanding of human movment only output a nestled json array of {"position_name":{position_data}} MAKE SURE TO CHANGE THE VALUES OF THE JSON TO MATCH THE POSITION IT SHOULD NOT BE ALL 0s'}   

        ]
}

response = requests.post(url, headers=headers, json=data)
result = response.json()

print(result["result"]["response"])