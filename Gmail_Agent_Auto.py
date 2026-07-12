import os
import imaplib
import email
from email.header import decode_header
from twilio.rest import Client
import google.generativeai as genai

# --- Configuration & Credentials pulled from the Cloud Environment ---
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
FROM_WHATSAPP = os.getenv("FROM_WHATSAPP", "whatsapp:+14155238886") # Default Twilio Sandbox
TO_WHATSAPP = os.getenv("TO_WHATSAPP")

# Initialize AI Client
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.5-flash")

def extract_body(msg):
    """Recursively extracts plain text body from email."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                try:
                    body = part.get_payload(decode=True).decode(errors="ignore")
                    break
                except:
                    pass
    else:
        body = msg.get_payload(decode=True).decode(errors="ignore")
    return " ".join(body.split())[:1200] # Cap text length per email

def clean_header(msg, header_name):
    """Decodes messy email headers smoothly."""
    raw_header = msg[header_name]
    if not raw_header:
        return f"(No {header_name})"
    decoded, encoding = decode_header(raw_header)[0]
    if isinstance(decoded, bytes):
        return decoded.decode(encoding or "utf-8", errors="ignore")
    return str(decoded)

def run_agent():
    try:
        # 1. Connect to Gmail (Writable mode to update flags)
        print("Connecting to Gmail...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("INBOX", readonly=False) 
        
        # Search for unread emails
        status, response = mail.search(None, "UNSEEN")
        email_ids = response[0].split()
        
        if not email_ids:
            print("No new unread emails found. Exiting.")
            mail.logout()
            return
            
        print(f"Found {len(email_ids)} unread email(s). Processing...")
        email_data_dump = []
        
        # Process up to the 5 most recent unread emails to prevent massive messages
        for e_id in email_ids[-5:]:
            status, msg_data = mail.fetch(e_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    sender = clean_header(msg, "From")
                    subject = clean_header(msg, "Subject")
                    body_text = extract_body(msg)
                    
                    email_data_dump.append(f"From: {sender}\nSubject: {subject}\nBody: {body_text}")
                    
                    # 🛑 CRITICAL STEP: Mark this email as read so it isn't picked up again next run
                    mail.store(e_id, "+FLAGS", "\\Seen")
        
        mail.close()
        mail.logout()
        
        # 2. Generate Summary with Gemini
        print("Generating AI summary...")
        all_emails_text = "\n\n=========================\n\n".join(email_data_dump)
        prompt = (
            "You are a personal digital assistant. Review the following unread emails and provide a "
            "highly concise, scannable executive digest using bullet points. "
            "Bold the sender's name. Use emojis where appropriate. "
            "Separate different email threads with a clean line break. "
            "If there is an explicit action item, task, or deadline, highlight it with an alert emoji. "
            f"Emails:\n\n{all_emails_text}"
        )
        
        response = model.generate_content(prompt)
        summary_text = response.text
        
        # 3. Disseminate via WhatsApp
        print("Sending to WhatsApp via Twilio...")
        twilio_client = Client(TWILIO_SID, TWILIO_TOKEN)
        
        final_payload = f"📬 *Your 4-Hour Email Digest* 📬\n\n{summary_text}"
        
        message = twilio_client.messages.create(
            body=final_payload,
            from_=FROM_WHATSAPP,
            to=TO_WHATSAPP
        )
        print(f"🎉 Success! Agent completed loop. Message ID: {message.sid}")
        
    except Exception as e:
        print(f"❌ Automation failed: {e}")

if __name__ == "__main__":
    run_agent()

