Features
├── Dashboard
│   ├── Overview Metrics ( with filtering )
|   ├── Live calls 
|   ├── Total calls
|   ├── Live chat
|   ├── Total chats
|   ├── Message source analytics (Graph view - agents)
|   ├── Agent Wise share
|   └── Total Metrics 
│
├── Agent
|   ├── Agent info 
|   |   ├── Total Agents
|   |   ├── Active Agents 
|   |   ├── Inactive Agents
|   |   ├── Connected voice Channels
|   |   └── Connected whatsapp Channels
|   |   
│   ├── Agent Search & Filtering
│   │   └── Keyword Search
|   |  
│   ├── Add Agent Button
│   │   ├── Blank agent  
|   │   │   ├── Agent Name
|   │   │   ├── Description
|   │   |   ├── Web urls (for scraping)
|   │   |   ├── File upload (Knowledge base - PDFs, TXT, csv, Doc)
|   |   |   ├── Conversation Starters
|   |   |   ├──Logic    
|   |   |   └──Instructions 
|   |   ├── Role type(task)
|   │   │   ├── Agent Name
|   │   │   ├── Description
|   │   |   ├── Web urls (for scraping)
|   |   |   ├── File upload (Knowledge base - PDFs, TXT, csv, Doc)
|   |   |   ├── Conversation Starters
|   |   
│   └── Agent list
│       ├── Agent name, role
|       ├── Type 
│       ├── Status
|       ├── Channels (number)
|       ├── tools
|       ├── Actions (edit)
|       |       ├── Agent name
|       |       ├── Description
|       |       ├── Description
|       |       ├── Web urls crawled
|       |       ├── File uploaded (Knowledge base - PDFs, TXT, csv, Doc)
|       |       ├── Conversation Starters
|       |       ├──Logic    
|       |       └──Instructions 
│       ├── Actions (delete) deletes whole agent
|
├── Channel (Omni Dashboard) (It will be not in Fast API)
|   ├── Channel config (Whatsapp, Voice)
|   |
│   ├── channel Search & Filtering
│   │   └── Keyword Search
|   | 
│   └── Channel list
│       ├── Channel name
|       ├── Type
|       ├── Agent 
│       └── Status
|
├── Knowledge Base 
|   ├── List 
|       ├── name (pdf, doc, txt,web urls, img url, video url, location link)
|       ├── agent linked
|       ├── chunks 
|       ├── source (pdf, web, doc, txt)
|       ├── status (draft, saved, active)
|       ├── created date
|       ├── Action buttons
|               ├── view 
|               ├── delete
|
├── Tools 
|   ├── Send Flow Message
|   |   Action Button (Click to visit Website, Click to call)
|   |   Webhook Config
|   |   Schedule (Calendar Type)
|   |   Suggestion (Accordion FAQ)
|
|
├── Reports
|       ├── Calls (number to reports)
|              ├── caller
|              ├── number 
|              ├── agent
|              ├── duration 
|              ├── messages
|              ├── response 
|              ├── status 
|              └── actions (delete)    
|           
|
├── Billings etc...
