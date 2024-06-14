import json
import aiohttp
import aiosqlite
import asyncio
from api_call_util import make_llm_api_call
from dotenv import load_dotenv
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import certifi
from datetime import datetime
import uuid
import random

os.environ['SSL_CERT_FILE'] = certifi.where()

load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
origins = [
    "http://www.seeking.domains",
    "https://www.seeking.domains",
    "https://seeking.domains",
    "http://seeking.domains",
    "https://seeking-domains.vercel.app",
    "https://be.seeking.domains" 
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    async with aiosqlite.connect('available_domains.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS available_domains (
                                domain TEXT UNIQUE,
                                priority_in_ranking INTEGER,
                                created_at TEXT,
                                search_request_id TEXT
                            )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS search_requests (
                                id TEXT PRIMARY KEY,
                                request_content TEXT,
                                created_at TEXT
                            )''')
        await db.commit()

@app.get("/available_domains")
async def get_available_domains(
    search_request_id: str = None,
    page: int = 1,
    page_size: int = 64,
    tld: str = None,
    char_length: int = None,
    char_length_op: str = None  # 'eq', 'gt', 'lt'
):
    query = "SELECT domain, priority_in_ranking, created_at FROM available_domains"
    params = []
    conditions = []

    if search_request_id:
        conditions.append("search_request_id = ?")
        params.append(search_request_id)

    if tld:
        conditions.append("domain LIKE ?")
        params.append(f"%.{tld}")

    if char_length and char_length_op:
        if char_length_op == 'eq':
            conditions.append("LENGTH(SUBSTR(domain, 1, INSTR(domain, '.') - 1)) = ?")
        elif char_length_op == 'gt':
            conditions.append("LENGTH(SUBSTR(domain, 1, INSTR(domain, '.') - 1)) > ?")
        elif char_length_op == 'lt':
            conditions.append("LENGTH(SUBSTR(domain, 1, INSTR(domain, '.') - 1)) < ?")
        params.append(char_length)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " LIMIT ? OFFSET ?"
    params.extend([page_size, (page - 1) * page_size])

    async with aiosqlite.connect('available_domains.db') as db:
        async with db.execute(query, params) as cursor:
            domains = await cursor.fetchall()
            async with db.execute("SELECT COUNT(*) FROM available_domains" + (" WHERE " + " AND ".join(conditions) if conditions else ""), params[:len(conditions)]) as count_cursor:
                total_count = (await count_cursor.fetchone())[0]

    total_pages = (total_count + page_size - 1) // page_size

    # Randomize the order of domains
    random.shuffle(domains)

    return JSONResponse(content={
        "domains": [{"domain": domain[0], "priority_in_ranking": domain[1], "created_at": domain[2]} for domain in domains],
        "pagination": {
            "current_page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_count": total_count
        }
    })

@app.post("/generate_and_check_domains")
async def generate_and_check_domains(request: dict):
    try:
        request_content = request.get("request")
        similar_to = request.get("similar_to")
        word_length = request.get("word_length")
        accepted_tlds = request.get("accepted_tlds")

        if not request_content:
            raise HTTPException(status_code=400, detail="Request content is missing")

        search_request_id = str(uuid.uuid4())
        await store_search_request(search_request_id, request_content)

        domain_names = await generate_domain_names(request_content, similar_to, word_length, accepted_tlds)
        available_domains = await check_domain_availability(domain_names)
        await store_available_domains(available_domains, search_request_id)
        
        return JSONResponse(content={
            "domains": [{"domain": domain, "priority_in_ranking": None, "created_at": datetime.utcnow().isoformat()} for domain in available_domains],
            "search_request_id": search_request_id,
            "domains_found": len(available_domains)
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/check_domain_availability")
async def check_single_domain_availability(domain: str):
    try:
        available = await check_domain_availability([domain])
        return JSONResponse(content={"domain": domain, "available": domain in available})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def generate_domain_names(request, similar_to, word_length, accepted_tlds):
    messages = [
        {
            "role": "system",
            "content": """ 
            
            
        YOU ARE AN EXPERT UNIQUE BRAND NAME GENERATOR. BASED ON THE REQUEST & ADDITIONAL PROVIDED INFORMATION GENERATE 10 DOMAINS FOR THE USER! FULLFILL HIS REQUEST!

# Rules for Creating Effective Startup Names

## 1. Short and Memorable:
- **Keep names short**: Ideally 2-3 syllables.
- **Easy to spell and pronounce**.

## 2. Pseudowords:
- **Create names without pre-existing meanings** but that sound like real words.
- **Avoid common words or phrases** to ensure uniqueness.

## 3. Unique Sound:
- **Use uncommon letter combinations** to create a unique sound.
- **Pass the "radio test"**: The name should be easy to say and understand when heard.

## 4. Flexible for Branding:
- **Easily adaptable** into logos, taglines, and branding materials.
- **Universal appeal**: Avoid associating with a specific culture or language.

## 5. Phonetically Pleasing:
- **Blend vowels and consonants** in a pleasing manner.
- **Avoid harsh or difficult-to-pronounce** letter combinations.

## 6. Neutral and Unbiased:
- **Avoid names with positive or negative connotations** in any language or culture.
- **Ensure no existing trademark** or association with unwanted entities.

# Examples 

## Simple Patterns:
- **Google**: C-V-C-C-V (Goo-gle)
- **Rolex**: C-V-C-V-C (Ro-lex)
- **Zynga**: C-V-C-C-V (Zyn-ga)

## Repetition and Symmetry:
- **Monzo**: C-V-C-C-V (Mon-zo)
- **Trello**: C-V-C-C-V (Tre-llo)
- **Asana**: V-C-V-C-V (A-sa-na)

## Innovative Blending:
- **Lululemon**: C-V-C-V-C-V-C (Lu-lu-le-mon)
- **Vistara**: C-V-C-C-V-C (Vis-ta-ra)
- **Zynlo**: C-V-C-C-V (Zyn-lo)
- **Nexora**: C-V-C-V-C (Nex-o-ra)

# Examples
- **Alixor**
- **Vorkel**
- **Zafira**
- **Lopio**
- **Radano**
- **Genza**
- **Mikro**
- **Zorina**
- **Velixo**
- **Jopari**



# Tips for Creating Your Own Names
- **Start with a Consonant or Vowel**: Mix and match styles.
- **Try Repetition**: Using the same letters or sounds.
- **Balance Hard and Soft Sounds**: Ensure a smooth and catchy name.
- **Test the Name**: Speak it out loud and solicit feedback.

    Find creative combinations to domains such as 'Find.domains' -> like combine words with suitable existing TLDs.

Using these rules and the expanded list, you can generate unique and effective startup names that resonate and grow on users.

        Generate a list of 100 domain names. OUTPUT IN JSON. OUTPUT WITHIN `domain_names`. 

        YOU ARE ONLY PERMITTED TO OUTPUT WITH THE FOLLOWING TLDS:

        Example JSON Output:
        ```json
        {
            "domain_names": ["example1.tld", "example2.tld", "example3.tld", "gpu.tld"]
        }
        ```
        THIS IS THE EXACT JSON OUTPUT YOU HAVE TO FOLLOW! DO NOT ADD ANYTHING ELSE.

        Think step by step and deeply.

                    """
        },
        {
            "role": "user",
            "content": f"""

            FOLLOW THE FOLLOWING REQUEST!! DO NOT RETURN THE EXAMPLES YOU HAVE, INSTEAD RESEARCH FOR THE REQUEST:
            REQUEST: {request}
            FIND SIMILAR TO: {similar_to}
            WORD LENGTH: {word_length} Characters
            ACCEPTED TLDS: {accepted_tlds}
        
            """
        }
    ]
    response = await make_llm_api_call(messages, model_name="gpt-4o", json_mode=True, temperature=0.5)
    domain_names = json.loads(response['choices'][0]['message']['content'])['domain_names']
    return domain_names

async def check_domain_availability(domain_names_with_tlds):
    api_key = os.getenv("NAMECHEAP_API_KEY")
    api_user = os.getenv("NAMECHEAP_API_USER")
    client_ip = os.getenv("NAMECHEAP_CLIENT_IP")
    available_domains = []

    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    async with aiohttp.ClientSession() as session:
        for domain_batch in (domain_names_with_tlds[i:i+20] for i in range(0, len(domain_names_with_tlds), 20)):
            payload = {
                "ApiUser": api_user,
                "ApiKey": api_key,
                "UserName": api_user,
                "Command": "namecheap.domains.check",
                "ClientIp": client_ip,
                "DomainList": ",".join(domain_batch)
            }
            try:
                async with session.post("https://api.namecheap.com/xml.response", headers=headers, data=payload) as response:
                    response_text = await response.text()
                    response.raise_for_status()  # Raise an exception for HTTP errors
                    available_domains += parse_namecheap_response(response_text)
            except aiohttp.ClientError as e:
                raise HTTPException(status_code=500, detail=f"Request failed: {e}")

    return available_domains

def parse_namecheap_response(xml_response):
    import xml.etree.ElementTree as ET
    available_domains = []
    root = ET.fromstring(xml_response)
    namespace = {'ns': 'http://api.namecheap.com/xml.response'}
    for domain_info in root.findall(".//ns:DomainCheckResult", namespace):
        if domain_info.get('Available') == 'true':
            available_domains.append(domain_info.get('Domain'))
    return available_domains

async def store_search_request(search_request_id, request_content):
    async with aiosqlite.connect('available_domains.db') as db:
        await db.execute("INSERT INTO search_requests (id, request_content, created_at) VALUES (?, ?, ?)", (search_request_id, request_content, datetime.utcnow().isoformat()))
        await db.commit()

async def store_available_domains(domains, search_request_id):
    async with aiosqlite.connect('available_domains.db') as db:
        for domain in domains:
            try:
                await db.execute("INSERT INTO available_domains (domain, created_at, search_request_id) VALUES (?, ?, ?)", (domain, datetime.utcnow().isoformat(), search_request_id))
            except aiosqlite.IntegrityError:
                # Domain already exists in the database
                pass
        await db.commit()

async def main():
    request = "Test"
    domain_names = await generate_domain_names(request)
    available_domains = await check_domain_availability(domain_names)
    search_request_id = str(uuid.uuid4())
    await store_search_request(search_request_id, request)
    await store_available_domains(available_domains, search_request_id)
    print(f"Available domains: {available_domains}")  # Ensure available domains are logged

if __name__ == "__main__":
    asyncio.run(main())
