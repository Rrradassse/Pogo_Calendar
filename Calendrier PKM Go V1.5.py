# ==============================================================================
# 🛠️ SCRIPT DE RÉCUPÉRATION ULTIME POKÉMON GO (FIX NOUVEL AN + EVENTS DISPARUS)
# ==============================================================================

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Event
from datetime import datetime, timedelta
import re
import unicodedata
import os
import time

# --- CONFIGURATION ---
FILE_NAME = "pogo_calendar_Mag.ics"
MOIS_FR = {
    'janvier': 1, 'fevrier': 2, 'mars': 3, 'avril': 4, 'mai': 5, 'juin': 6,
    'juillet': 7, 'aout': 8, 'septembre': 9, 'octobre': 10, 'novembre': 11, 'decembre': 12
}

# --- OUTILS DE PARSING ---
def clean_slug(text):
    text = text.lower()
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    return text

def generate_uid(source, date_str, name):
    # ID unique pour éviter les doublons (ex: MGX-20260217-nouvelan)
    clean_name = re.sub(r'[^a-zA-Z0-9]', '', name).lower()[:15]
    return f"{source}-{date_str}-{clean_name}@pogo.script"

def parse_complex_date(date_text, current_year, default_month):
    """
    Le Cœur du problème : Comprendre toutes les façons d'écrire une date.
    Ex: "17 février", "Du 17 au 21 février", "17 et 18 février"
    """
    text = date_text.lower().replace("1er", "1").replace("février", "fevrier").replace("août", "aout").replace("décembre", "decembre")
    
    # 1. Trouver le mois (si écrit en toutes lettres)
    month = default_month
    for m_name, m_id in MOIS_FR.items():
        if m_name in text:
            month = m_id
            break
            
    # 2. Trouver les jours (tous les chiffres)
    days = [int(d) for d in re.findall(r'\b(\d{1,2})\b', text)]
    
    if not days: return None, None
    
    start_day = days[0]
    # Gestion simple des années (si on est en décembre et qu'on lit janvier)
    year = current_year
    
    start_dt = datetime(year, month, start_day)
    end_dt = start_dt # Par défaut, dure 1 jour
    
    # Gestion des plages "Au" ou "Et"
    if len(days) > 1:
        end_day = days[-1]
        # Cas complexe : cheval sur 2 mois (ex: 30 jan au 2 fév)
        if end_day < start_day:
            next_month = month + 1 if month < 12 else 1
            next_year = year if month < 12 else year + 1
            end_dt = datetime(next_year, next_month, end_day)
        else:
            end_dt = datetime(year, month, end_day)
            
    return start_dt, end_dt

# --- SCRAPER 1 : MARGXT (LE SAUVEUR POUR LE NOUVEL AN) ---
def get_margxt_ultimate():
    print("🌍 1. Scan Margxt (Passé/Futur + Toutes catégories)...")
    scraped = []
    seen = set()
    today = datetime.now()
    
    # On scanne large : -2 mois à +5 mois
    months_to_scan = []
    for i in range(-2, 24):
        d = today + timedelta(days=i*30)
        months_to_scan.append((d.year, d.month))
    months_to_scan = sorted(list(set(months_to_scan))) # Dédoublonnage

    for year, month in months_to_scan:
        # Construction URL
        m_name = [k for k, v in MOIS_FR.items() if v == month][0]
        url = f"https://www.margxt.fr/le-planning-des-evenements-de-{m_name}-{year}-dans-pokemon-go/"
        
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
            if res.status_code != 200: continue
            
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # CIBLES : On veut TOUT (y compris "événements" qui contient le Nouvel An)
            targets = {
                "heures vedettes": {"e": "⭐️", "h": (18, 19)},
                "heures de raids": {"e": "⚔️", "h": (18, 19)},
                "lundi dynamax":   {"e": "💥", "h": (18, 19)},
                "community day":   {"e": "💿", "h": (14, 17)},
                "événements":      {"e": "📅", "h": (10, 20)}, # <--- C'est lui qui attrape le Nouvel An
                "raids légendaires": {"e": "🐲", "h": (10, 20)},
                "méga-raids":      {"e": "🧬", "h": (10, 20)}
            }
            
            # Scan des titres H2/H3
            for t in soup.find_all(['h2', 'h3']):
                txt_cat = t.get_text().lower()
                conf = next((v for k, v in targets.items() if k in txt_cat), None)
                
                if conf:
                    table = t.find_next('table')
                    if table:
                        for row in table.find_all('tr')[1:]:
                            cols = row.find_all(['td', 'th'])
                            if len(cols) >= 2:
                                d_txt = cols[0].get_text(" ", strip=True)
                                nom = cols[1].get_text(" ", strip=True)
                                bonus = cols[2].get_text(" ", strip=True) if len(cols) > 2 else ""

                                # Parsing Date Robuste
                                s_dt, e_dt = parse_complex_date(d_txt, year, month)
                                if not s_dt: continue
                                
                                # Heures
                                s_dt = s_dt.replace(hour=conf['h'][0], minute=0)
                                e_dt = e_dt.replace(hour=conf['h'][1], minute=0)

                                # Signature
                                uid = generate_uid("MGX", s_dt.strftime("%Y%m%d"), nom)
                                
                                scraped.append({
                                    "uid": uid,
                                    "summary": f"{conf['e']} {nom}",
                                    "start": s_dt,
                                    "end": e_dt,
                                    "desc": f"🎁 {bonus}\n🔗 {url}"
                                })
                                print(f"   + [Margxt] Trouvé : {nom} ({s_dt.strftime('%d/%m')})")

        except Exception as e: continue
    return scraped

# --- SCRAPER 2 : NIANTIC (LE DÉTAILLANT) ---
def get_niantic_ultimate():
    print("🌍 Scan Niantic (Listing Officiel)...")
    scraped = []
    
    # 1. On lit d'abord la LISTE OFFICIELLE /events/ (Les dates y sont toujours justes)
    try:
        res = requests.get("https://pokemongo.com/fr/events/", headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # On cherche toutes les cartes d'événements
        for card in soup.find_all('div', class_='event-card'): # Selecteur générique, on adapte au contenu
            # Fallback : Niantic utilise souvent des balises <pg-date-format> directement dans la liste
            date_tag = card.find('pg-date-format') or card.find_next('pg-date-format')
            link_tag = card.find('a')
            
            # Si on trouve une date et un lien dans la liste
            if date_tag and link_tag and date_tag.has_attr('startdate'):
                href = link_tag['href']
                full_link = f"https://pokemongo.com{href}" if not href.startswith('http') else href
                title = link_tag.get_text(strip=True) or "Événement Niantic"
                
                # Récupération des dates (Fiable à 100% depuis la liste)
                s_dt = datetime.strptime(date_tag['startdate'], "%Y-%m-%d").replace(hour=10)
                e_str = date_tag.get('enddate')
                e_dt = datetime.strptime(e_str, "%Y-%m-%d").replace(hour=20) if e_str else s_dt.replace(hour=20)
                
                # On va chercher l'image et les bonus dans la page détail
                try:
                    art_res = requests.get(full_link, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                    art_soup = BeautifulSoup(art_res.text, 'html.parser')
                    img = art_soup.find('img')['src'] if art_soup.find('img') else ""
                    
                    content = art_soup.find('section', class_=re.compile(r'body|content')) or art_soup
                    bonuses = [li.get_text(" ", strip=True) for li in content.find_all('li') 
                               if any(k in li.get_text() for k in ["XP", "Bonbon", "Poussière", "Distance"])]
                    desc = "\n• ".join(bonuses[:6])
                except:
                    img = ""
                    desc = "Voir détails sur le site."

                uid = generate_uid("NIA", s_dt.strftime("%Y%m%d"), title)
                scraped.append({
                    "uid": uid,
                    "summary": f"🎉 {title}",
                    "start": s_dt,
                    "end": e_dt,
                    "desc": f"🖼️ {img}\n📝 {desc}\n🔗 {full_link}"
                })
    except Exception as e:
        print(f"Erreur Listing Events: {e}")

    # 2. On complète avec les NEWS (Pour ce qui n'est pas encore dans l'agenda)
    # (Copie simplifiée de l'ancien scanner news pour ne rien rater)
    try:
        res = requests.get("https://pokemongo.com/fr/news/", headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(res.text, 'html.parser')
        for a in soup.find_all('a', href=re.compile(r'/news/'))[:8]:
            full_link = f"https://pokemongo.com{a['href']}"
            # Si on l'a déjà trouvé dans /events/, on passe
            if any(ev['desc'].endswith(full_link) for ev in scraped): continue
            
            try:
                # Analyse rapide de la page news
                art = requests.get(full_link, headers={"User-Agent": "Mozilla/5.0"}).text
                if 'startdate="' in art:
                    s_str = re.search(r'startdate="([0-9-]+)"', art).group(1)
                    titre = re.search(r'<title>(.*?)</title>', art).group(1).split('|')[0].strip()
                    
                    if any(x in titre.lower() for x in ["vedette", "raids", "dev diary"]): continue
                    
                    dt = datetime.strptime(s_str, "%Y-%m-%d").replace(hour=10)
                    uid = generate_uid("NIA", s_str.replace("-",""), titre)
                    scraped.append({
                        "uid": uid, 
                        "summary": f"🎉 {titre}", 
                        "start": dt, 
                        "end": dt.replace(hour=20), 
                        "desc": f"🔗 {full_link}"
                    })
            except: continue
    except: pass
    
    return scraped

# --- MOTEUR PRINCIPAL ---
def main():
    # 1. Charger l'existant (Si le fichier existe)
    db = {}
    if os.path.exists(FILE_NAME):
        print(f"\n📂 Chargement de {FILE_NAME}...")
        try:
            with open(FILE_NAME, 'rb') as f:
                cal = Calendar.from_ical(f.read())
                for c in cal.walk():
                    if c.name == "VEVENT": db[str(c.get('UID'))] = c
        except: pass

    # 2. Scraper
    new_data = get_margxt_ultimate() + get_niantic_ultimate()

    # 3. Fusionner (Ajout ou Mise à jour)
    for item in new_data:
        e = Event()
        e.add('summary', item['summary'])
        e.add('dtstart', item['start'])
        e.add('dtend', item['end'])
        e.add('description', item['desc'])
        e.add('uid', item['uid'])
        
        db[item['uid']] = e # Écrase l'ancien ou crée le nouveau

    # 4. Sauvegarder
    cal = Calendar()
    cal.add('prodid', '-//PogoFinal//FR')
    cal.add('version', '2.0')
    cal.add('X-WR-CALNAME', 'PkmGo_Mag')
    cal.add('X-WR-TIMEZONE', 'Europe/Paris')
    
    
    for e in db.values():
        cal.add_component(e)

    with open(FILE_NAME, 'wb') as f:
        f.write(cal.to_ical())

    print(f"\n✅ TERMINÉ ! {len(db)} événements dans le calendrier.")
    print("👉 Les gros events (Niantic) et le Nouvel An (Margxt) devraient être là.")

if __name__ == "__main__":

    main()

