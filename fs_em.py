# -*- coding: utf-8 -*-


!pip install --upgrade google-auth-oauthlib google-auth-httplib2 google-api-python-client tldextract requests aiohttp beautifulsoup4



import gspread
from google.colab import auth
from google.auth import default
import requests
import re
import asyncio
import aiohttp
import multiprocessing
import pandas as pd
import json
from bs4 import BeautifulSoup
from urllib.parse import unquote, urljoin
import tldextract

# Extended configuration from app.py
IGNORE_DOMAINS = [
    "wix.com", "mysite.com", "domain.com", "example.com",
    "sentry.io", "wixpress.com", "squarespace.com",
    "wordpress.com", "email.com", "shopify.com"
]

COMMON_EMAIL_DOMAINS = [
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "aol.com", "icloud.com", "protonmail.com", "mail.com",
    "zoho.com", "yandex.com", "gmx.com"
]

CONTACT_PAGES = [
    "/contact", "/contact-us", "/contact.html", "/contact-us.html",
    "/about", "/about-us", "/about.html", "/about-us.html",
    "/get-in-touch", "/reach-us", "/connect", "/reach-out",
    "/our-team", "/team", "/support", "/help", "/info"
]

def validate_email(email):
    """Validate and clean email addresses"""
    email = email.strip().lower()

    # Ignore image files and other non-email strings
    if any(ext in email for ext in [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"]):
        return None

    # Remove invalid start/end characters
    email = re.sub(r'^[^a-zA-Z0-9]+|[^a-zA-Z0-9\.]+$', '', email)

    # Check email pattern and domain structure
    if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        parts = email.split('@')
        if len(parts) == 2 and "." in parts[1]:
            domain_part = parts[1]
            if not re.search(r'\d+x\d+', domain_part):
                return email
    return None

def get_domain(url):
    """Extract domain from URL"""
    try:
        extracted = tldextract.extract(url)
        return f"{extracted.domain}.{extracted.suffix}"
    except:
        return None

def clean_and_deduplicate_emails(emails_list):
    """Clean and deduplicate email list"""
    if not emails_list:
        return []

    clean_emails = set()
    for email in emails_list:
        valid_email = validate_email(email)
        if valid_email and not any(ignore_domain in valid_email for ignore_domain in IGNORE_DOMAINS):
            clean_emails.add(valid_email)

    # Similar deduplication logic from app.py
    emails_to_remove = set()
    final_emails = list(clean_emails)

    for i in range(len(final_emails)):
        for j in range(len(final_emails)):
            if i != j and final_emails[i] != final_emails[j]:
                email1_parts = final_emails[i].split('@')
                email2_parts = final_emails[j].split('@')

                if len(email1_parts) == 2 and len(email2_parts) == 2 and email1_parts[1] == email2_parts[1]:
                    username1, username2 = email1_parts[0], email2_parts[0]

                    if username1 in username2:
                        emails_to_remove.add(final_emails[j])
                    elif username2 in username1:
                        emails_to_remove.add(final_emails[i])

    final_cleaned = [email for email in final_emails if email not in emails_to_remove]
    return final_cleaned

async def fetch_emails(session, url):
    """Enhanced email extraction method"""
    try:
        # Ensure URL has proper prefix
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        domain = get_domain(url)
        emails_set = set()

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with session.get(url, headers=headers, timeout=15) as response:
            if response.status == 200:
                text = await response.text()
                soup = BeautifulSoup(text, "html.parser")

                # Multiple email extraction methods
                text_emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)

                # Mailto links
                mailto_emails = [unquote(a['href'].replace('mailto:', '').split('?')[0])
                                 for a in soup.find_all('a', href=True) if 'mailto:' in a['href']]

                # Script and meta tag emails
                script_emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                                           ' '.join([script.string for script in soup.find_all('script') if script.string]))

                meta_emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                                         ' '.join([meta.get('content', '') for meta in soup.find_all('meta')]))

                # Domain-based email extraction
                domain_emails = [email for email in (text_emails + mailto_emails + script_emails + meta_emails)
                                 if domain and domain in email]

                all_emails = text_emails + mailto_emails + script_emails + meta_emails

                # Clean and validate emails
                cleaned_emails = clean_and_deduplicate_emails(all_emails)

                # Prioritize domain-matched emails
                domain_matched_emails = [email for email in cleaned_emails if domain and domain in email]
                other_emails = [email for email in cleaned_emails if email not in domain_matched_emails]

                emails_set.update(domain_matched_emails + other_emails)

                return list(emails_set)[:5]  # Limit to top 5 emails
    except Exception as e:
        print(f"Error extracting emails from {url}: {e}")

    return ["No Email Found"]

# Rest of the script remains the same as your previous implementation
async def process_websites(websites):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_emails(session, url) for url in websites]
        return await asyncio.gather(*tasks)

def run_async_in_process(websites):
    return asyncio.run(process_websites(websites))

def process_sheet(spreadsheet_url):
    # Your existing sheet processing logic remains the same
    sh = gc.open_by_url(spreadsheet_url)
    for worksheet in sh.worksheets():
        print(f"Processing Sheet: {worksheet.title}")
        data = worksheet.get_all_values()
        if not data:
            continue

        headers = data[0]
        website_col_idx = next((i for i, col in enumerate(headers) if "website" in col.lower()), None)

        if website_col_idx is None:
            print("No website column found in sheet.")
            continue

        headers = data[0]
        data_rows = data[1:]

        websites = [row[website_col_idx] for row in data[1:] if row[website_col_idx]]

        # Use multiprocessing to run the async part in a separate process
        with multiprocessing.Pool(1) as pool:
            emails_list = pool.apply(run_async_in_process, args=(websites,))

        rows_to_delete = []

        # Process emails and update sheet
        for i, (row, emails) in enumerate(zip(data_rows, emails_list), start=1):
            if emails == ["No Email Found"]:
                # Mark this row for deletion
                rows_to_delete.append(i + 1)  # +1 to account for header row
            else:
                # Update emails in the next column
                for j, email in enumerate(emails):
                    worksheet.update_cell(i + 1 + j, website_col_idx + 2, email)

        # Delete rows with no emails (in reverse order to maintain correct indexing)
        if rows_to_delete:
            for row in sorted(rows_to_delete, reverse=True):
                worksheet.delete_rows(row)
            print(f"Deleted {len(rows_to_delete)} rows with no emails found.")

# Authenticate and run
auth.authenticate_user()
creds, _ = default()
gc = gspread.authorize(creds)

# Run the script (Replace with your Google Sheet URL)
spreadsheet_url = ""
process_sheet(spreadsheet_url)

print("✅ Done! Emails have been extracted and added to your sheet.")
