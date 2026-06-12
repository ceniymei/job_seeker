export interface Job {
  id: number;
  company_name: string;
  company_id: number;
  title: string;
  department: string | null;
  location: string;
  salary: string | null;
  description: string | null;
  job_url: string;
  status: string;
  raw_metadata: any;
  first_seen_at: string;
  last_seen_at: string;
}

export const MOCK_JOBS: Job[] = [
  {
    id: 101,
    company_name: "Google",
    company_id: 1,
    title: "Senior Staff Software Engineer, Gemini Brain Team",
    department: "Google DeepMind",
    location: "Mountain View, CA (Onsite)",
    salary: "$250,000 - $380,000 USD + Equity",
    description: `### Role Overview
We are seeking a Senior Staff Software Engineer to join the Gemini Brain Team. In this role, you will lead the architecture, design, and scale of our next-generation multimodal foundational models. You will collaborate closely with research scientists to implement high-performance training loops and highly optimized serving infrastructure on Google TPUs.

### Responsibilities
- Architect and build high-throughput distributed training frameworks for LLMs/LMMs spanning thousands of TPU accelerators.
- Optimize low-latency inference engines for Gemini models deployed across global edge and cloud pipelines.
- Partner with research scientists to rapidly prototype novel architecture enhancements, memory architectures, and attention mechanisms.
- Mentor senior engineers and define the technical roadmap for deep learning training platforms.

### Requirements
- BS/MS or PhD in Computer Science, Machine Learning, or a related quantitative field.
- 8+ years of industry experience building large-scale distributed systems or ML platforms.
- Deep expertise with JAX, PyTorch, or TensorFlow, and custom hardware accelerators (TPU/GPU).
- Excellent systems programming skills in C++, Python, or Rust.
- Proven track record of publishing at top-tier ML conferences (NeurIPS, ICML, CVPR) or shipping large foundational models to production.`,
    job_url: "https://careers.google.com/jobs/results/gemini-brain-staff-engineer",
    status: "active",
    raw_metadata: {
      source: "Google Careers API",
      scraper_version: "2.4.1",
      crawled_by: "ScrapeGraphAI-Google-Sniffer",
      network_info: {
        latency_ms: 184,
        proxy_ip: "104.244.75.12",
        status_code: 200
      },
      schema_details: {
        type: "JobPosting",
        context: "http://schema.org",
        job_immediate_start: true,
        job_category: "Engineering & Technology",
        hiring_org_linkedin: "https://linkedin.com/company/google"
      },
      extra_tags: ["GenAI", "JAX", "TPUs", "DeepMind"]
    },
    first_seen_at: "2026-06-08T10:00:00.000Z",
    last_seen_at: "2026-06-09T22:00:00.000Z"
  },
  {
    id: 102,
    company_name: "Apple",
    company_id: 2,
    title: "Staff Swift/C++ Engineer, CoreOS",
    department: "Interactive Media Group (IMG)",
    location: "Cupertino, CA (Hybrid)",
    salary: "$210,000 - $315,000 USD",
    description: `### Role Overview
Apple's Interactive Media Group (IMG) is looking for a senior systems engineer to design and implement core system-level libraries that power audio and video playback, spatial computation, and real-time communication across iOS, macOS, watchOS, and visionOS. You will work at the interface of low-level kernel services and high-level developer APIs.

### Responsibilities
- Design and develop robust, highly-concurrent system frameworks using Swift and C++.
- Optimize audio-video rendering engines for the next-generation spatial computing applications on Apple Vision Pro.
- Implement hardware-accelerated codecs, driver wrappers, and low-latency audio capture pipelines.
- Profile memory, GPU overheads, and battery impact utilizing Xcode Instruments.

### Requirements
- Strong proficiency in C++ (17/20) and modern Swift development.
- Deep knowledge of operating system concepts: thread synchronization, memory management, and I/O scheduling.
- Experience with media technologies such as CoreMedia, AVFoundation, Metal, or OpenGL.
- 5+ years of systems programming experience on UNIX-like platforms.`,
    job_url: "https://jobs.apple.com/en-us/details/200483281/staff-swift-cpp-engineer-coreos",
    status: "active",
    raw_metadata: {
      source: "Apple Jobs Portal",
      scraper_version: "2.4.0",
      crawled_by: "Playwright-Apple-DetailScraper",
      selectors_used: {
        title: "h1#job-title",
        salary: ".salary-range",
        description: ".jd-wrapper"
      },
      extracted_meta: {
        requisition_id: "REQ_200483281",
        hiring_manager_code: "US-CA-IMG-COREOS",
        visa_sponsorship: "available"
      }
    },
    first_seen_at: "2026-06-07T14:30:00.000Z",
    last_seen_at: "2026-06-09T21:45:00.000Z"
  },
  {
    id: 103,
    company_name: "Netflix",
    company_id: 3,
    title: "Senior Full Stack Engineer, Growth Systems",
    department: "Product Engineering",
    location: "Remote (US / Canada)",
    salary: "$450,000 - $600,000 USD (All-Cash)",
    description: `### Role Overview
Netflix's Growth Engineering team builds the acquisition, onboarding, and payment infrastructure that enables millions of members around the world to sign up and enjoy Netflix. We are seeking a Senior Full Stack Engineer to lead experiments and build core user-facing systems.

### Responsibilities
- Architect and execute A/B testing frameworks across the global signup and checkout flows.
- Build high-concurrency Node.js microservices and highly responsive React frontend components.
- Optimize core web vitals (LCP, FID, CLS) to improve conversion and user onboarding performance on low-bandwidth networks.
- Design database schemas and data pipelines with Cassandra, PostgreSQL, and Kafka.

### Requirements
- Experience building and maintaining highly scalable user-facing web applications.
- Strong knowledge of modern JavaScript/TypeScript, React, Node.js, and CSS.
- Proven experience with distributed caching (Redis), NoSQL databases, and stream processing.
- Analytical mindset with experience running statistical A/B test experiments.
- High degree of autonomy and alignment with the Netflix Culture.`,
    job_url: "https://jobs.netflix.com/jobs/3104928",
    status: "active",
    raw_metadata: {
      source: "Netflix Jobs API",
      scraper_version: "2.3.9",
      crawled_by: "JSON-API-Fetcher",
      data_payload: {
        posting_date: "2026-06-05",
        country_code: "US",
        primary_skill: "React/Node"
      }
    },
    first_seen_at: "2026-06-05T09:00:00.000Z",
    last_seen_at: "2026-06-09T18:00:00.000Z"
  },
  {
    id: 104,
    company_name: "Stripe",
    company_id: 4,
    title: "Principal Product Manager, Global Checkout",
    department: "Payments Org",
    location: "Singapore (Hybrid)",
    salary: "$180,000 - $245,000 SGD + Benefits",
    description: `### Role Overview
Stripe is building the economic infrastructure for the internet. As the Principal Product Manager for Global Checkout, you will define the roadmap for Stripe's pre-built payment UI components used by millions of businesses worldwide. Your mission is to make online checkout seamless, safe, and dynamically tailored to every buyer on Earth.

### Responsibilities
- Define and drive the multi-year vision, strategy, and roadmap for Stripe Checkout and Payment Element.
- Collaborate with engineering, design, and machine learning to build intelligent payment method routing and conversion optimization models.
- Engage with merchants from startups to Fortune 500 companies to understand their payment needs.
- Define success metrics and analyze checkout flows to increase global transaction success rates.

### Requirements
- 8+ years of product management experience, preferably in payments, e-commerce, or developer platforms.
- Technical background (e.g. Computer Science degree, or equivalent experience working closely with APIs and integration systems).
- Exceptional design intuition; passion for crafting polished developer and consumer experiences.
- Exceptional analytical and communication skills.`,
    job_url: "https://stripe.com/jobs/detail/principal-pm-checkout",
    status: "active",
    raw_metadata: {
      source: "Stripe Careers HTML",
      scraper_version: "2.4.2",
      crawled_by: "Playwright-Stripe-Crawler",
      debug_info: {
        cookies_saved: true,
        bypass_cloudflare: true,
        wait_for_selector: ".jobs-detail-content"
      }
    },
    first_seen_at: "2026-06-06T08:15:00.000Z",
    last_seen_at: "2026-06-09T20:30:00.000Z"
  },
  {
    id: 105,
    company_name: "OpenAI",
    company_id: 5,
    title: "Member of Technical Staff, Alignment Research",
    department: "Superalignment / Safety Org",
    location: "San Francisco, CA (Onsite)",
    salary: "$300,000 - $450,000 USD + Equity",
    description: `### Role Overview
OpenAI's Alignment team conducts research into aligning artificial general intelligence (AGI) systems with human intent and values. We are looking for researchers and engineers to build systems to automate alignment research, train AI systems to assist in evaluations, and scale scalable oversight methods.

### Responsibilities
- Design and execute experiments on Reinforcement Learning from Human Feedback (RLHF) and scalable supervision.
- Train large language models on reward modeling, red-teaming, and constitutional AI workflows.
- Develop scalable infrastructure to distribute model training and RLHF across massive compute clusters.
- Collaborate with safety policy experts to translate ethical guidelines into training objectives.

### Requirements
- Deep research or engineering background in machine learning, particularly with PyTorch and distributed training.
- Strong intuition for model evaluation, scaling laws, and generative model behaviors.
- Experience with PyTorch, CUDA kernel optimizations, or large-scale data engineering.
- Deep passion for the safety, alignment, and social impact of advanced AI systems.`,
    job_url: "https://openai.com/careers/mts-alignment-research",
    status: "active",
    raw_metadata: {
      source: "OpenAI Careers Page",
      scraper_version: "2.4.1",
      crawled_by: "Puppeteer-OpenAI-Watcher",
      meta: {
        department_slug: "safety-alignment",
        remote_friendly: false
      }
    },
    first_seen_at: "2026-06-08T09:00:00.000Z",
    last_seen_at: "2026-06-09T22:00:00.000Z"
  }
];
