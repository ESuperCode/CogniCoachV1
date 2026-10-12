import json
import requests
import re
with open(r"C:\Users\bshanbhag\OneDrive - Eastside Preparatory School\Downloads\ECOACH\SeperateBuild-Tests\drill_to_json\movments.json", "r", encoding="utf-8") as file:
    MOVEMENT_DATA = json.load(file)
def call(user,system):
    API_KEY = "csk-4ecm9mj5wfrmy986h92jtrcx6y8pcjxw9fk3n4yndp528ynd"
    URL = "https://api.cerebras.ai/v1/chat/completions"


    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
    "model": "llama3.1-8b", 
    "messages": [
        {"role":"user", "content":user},
        {"role":"system", "content":system}
    ]
       
    }


    response = requests.post(URL, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        result = response.json()
        print(result['choices'][0]['message']['content'])
        return result['choices'][0]['message']['content']
    else:
        print(f"Error {response.status_code}: {response.text}")
        return


def parse_tags(text: str) -> list:    
    base_text = text.split('#')[0]
    include_match = re.search(r'#include:([^#]+)', text)
    exclude_match = re.search(r'#exclude:([^#]+)', text)
    include_val = include_match.group(1) if include_match else ''
    exclude_val = exclude_match.group(1) if exclude_match else ''
    com=[]
    if ',' in exclude_val:
        exs=exclude_val.split(',')         
        for ex in exs:
            dims=ex.split('.')        
            for dim in dims[1].split(''):
                com.append(dims[0]+dim)
    else:
        dims=ex.split('.')        
        for dim in dims[1].split(''):
            com.append(dims[0]+dim)    
       
    return [base_text, include_val, com]

def compiler(commands):
    animation=[]
    for line in commands:
        jcode=[{},{},{},{}]
        for movment in line:
            jcode = [{**d2, **d1} for d1, d2 in zip(jcode, MOVEMENT_DATA[movment])]
        animation+=jcode
    return json.dumps(animation)
def format(ai_response):
    lines = [(line.strip()).split(" ") for line in ai_response.splitlines()]
    return lines
def main(drill):
    response=call("","")
    response=format(response)
    return compiler(response)
print(compiler(format("walking_lower#exclude:spine.xyz walking_upper")))
    
