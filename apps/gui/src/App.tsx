import { useState, useEffect, useMemo } from "react";
import { 
  Search, 
  Briefcase, 
  MapPin, 
  DollarSign, 
  Clock, 
  ExternalLink, 
  AlertCircle, 
  RefreshCw, 
  ChevronDown, 
  ChevronUp, 
  Database,
  Building,
  CheckCircle,
  HelpCircle,
  Sparkles,
  UploadCloud,
  X
} from "lucide-react";
import { MOCK_JOBS, Job } from "./mockData";

export default function App() {
  // Data & state
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [apiStatus, setApiStatus] = useState<"checking" | "online" | "offline">("checking");
  const [useMockData, setUseMockData] = useState<boolean>(true);
  const [metadataExpanded, setMetadataExpanded] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // AI resume matching state
  const [resumeText, setResumeText] = useState<string>("");
  const [aiMatching, setAiMatching] = useState<boolean>(false);
  const [aiJobs, setAiJobs] = useState<(Job & { match_score: number; match_reason: string })[]>([]);
  const [isAiMode, setIsAiMode] = useState<boolean>(false);
  const [aiLoadingStep, setAiLoadingStep] = useState<string>("Parsing resume content...");
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);

  const runMockAiMatch = (_text: string) => {
    setAiMatching(true);
    setAiLoadingStep("Analyzing resume semantics...");
    
    setTimeout(() => {
      setAiLoadingStep("Filtering candidates from 800+ jobs...");
      
      setTimeout(() => {
        setAiLoadingStep("Refining matches with LLM...");
        
        setTimeout(() => {
          const source = useMockData ? MOCK_JOBS : jobs;
          if (source.length === 0) {
            setAiMatching(false);
            setErrorMsg("No job data available for matching.");
            return;
          }
          
          const shuffled = [...source].sort(() => 0.5 - Math.random());
          const selected = shuffled.slice(0, Math.min(4, shuffled.length));
          
          const mockReasons = [
            "Your resume showcases outstanding full-stack development skills, especially with React and Node.js. This role has high demands for frontend component architecture and high-concurrency API integrations, which align perfectly with your background. Your agile teamwork experience is also a strong plus.",
            "This position focuses on system-level architecture and core backend services. Your experience with Python/Go and SQL/NoSQL database design fits the microservices platform this team is building. Your database performance tuning experience will help you stand out.",
            "This role requires an engineer with strong product thinking and cross-functional collaboration. Your resume indicates you have led several systems from 0 to 1, showing excellent requirements analysis and code governance habits, which will help establish standards in this startup team.",
            "This position focuses on cloud-native deployments and CI/CD pipeline maintenance. Your Docker containerization practices and AWS experience align perfectly with the group's current tech stack, allowing you to quickly solve their automation pain points."
          ];
          
          const mockScores = [96, 92, 87, 81];
          
          const matched = selected.map((job, idx) => ({
            ...job,
            match_score: mockScores[idx] || 85,
            match_reason: mockReasons[idx] || "The candidate has a solid technical foundation in this area, with excellent project outcomes that align closely with the core responsibilities of this role."
          }));
          
          setAiJobs(matched as any);
          setIsAiMode(true);
          setAiMatching(false);
          if (matched.length > 0) {
            setSelectedJobId(matched[0].id);
          }
        }, 1200);
      }, 1000);
    }, 800);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    setSelectedFileName(file.name);
    
    if (file.name.endsWith(".txt") || file.name.endsWith(".md")) {
      const reader = new FileReader();
      reader.onload = (event) => {
        const text = event.target?.result as string;
        setResumeText(text);
      };
      reader.readAsText(file);
    } else if (file.name.endsWith(".pdf")) {
      if (useMockData || apiStatus === "offline") {
        setResumeText(`[PDF Resume Imported: ${file.name}]\nThis resume belongs to a software engineer with fullstack/backend development experience, proficient in React, Node.js, Python, PostgreSQL, etc.`);
      } else {
        setResumeText(`[Successfully loaded PDF file: ${file.name}]. Click "Start Match" below.`);
        (window as any)._uploadedFile = file;
      }
    } else {
      alert("Only .txt, .md, and .pdf resume files are supported.");
    }
  };

  const handleAiMatch = async () => {
    const file = (window as any)._uploadedFile;
    const hasText = resumeText.trim() && !resumeText.startsWith("[Successfully loaded PDF file");
    
    if (!file && !hasText) {
      alert("Please paste your resume content or upload a resume file first.");
      return;
    }
    
    setAiMatching(true);
    setErrorMsg(null);
    
    if (useMockData || apiStatus === "offline") {
      runMockAiMatch(resumeText);
      return;
    }
    
    try {
      let data;
      if (file) {
        setAiLoadingStep("Uploading and parsing PDF resume...");
        const formData = new FormData();
        formData.append("file", file);
        
        const response = await fetch("http://localhost:8000/match-jobs/file", {
          method: "POST",
          body: formData
        });
        
        if (!response.ok) {
          throw new Error(`Upload and match failed: HTTP ${response.status}`);
        }
        data = await response.json();
      } else {
        setAiLoadingStep("Sending resume for LLM evaluation...");
        const response = await fetch("http://localhost:8000/match-jobs/text", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ resume_text: resumeText })
        });
        
        if (!response.ok) {
          throw new Error(`Matching failed: HTTP ${response.status}`);
        }
        data = await response.json();
      }
      
      if (data.length === 0) {
        setErrorMsg("No highly matching jobs found after LLM analysis. Try refining your resume description or adding more technical keywords.");
        setAiMatching(false);
        return;
      }
      
      setAiJobs(data);
      setIsAiMode(true);
      if (data.length > 0) {
        setSelectedJobId(data[0].id);
      }
    } catch (err: any) {
      console.error("AI matching failed:", err);
      setErrorMsg("Failed to call local LLM match API. Automatically downgraded to Mock match mode.");
      runMockAiMatch(resumeText);
    } finally {
      setAiMatching(false);
      (window as any)._uploadedFile = null;
    }
  };

  // Filter state
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedCompanies, setSelectedCompanies] = useState<string[]>([]);
  const [selectedLocation, setSelectedLocation] = useState<string>("all");
  const [selectedStatus, setSelectedStatus] = useState<string>("all");

  // Fetch data function
  const fetchData = async () => {
    setLoading(true);
    setErrorMsg(null);
    setApiStatus("checking");
    
    try {
      // Try to connect to local FastAPI backend
      const response = await fetch("http://localhost:8000/jobs?status=all");
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      
      setJobs(data);
      setApiStatus("online");
      
      // Check if all jobs are 'Unknown Position' (usually means extraction is needed)
      const allUnknown = data.length > 0 && data.every((j: any) => j.title === "Unknown Position");
      if (allUnknown) {
        setErrorMsg("Detected that all jobs in the database are 'Unknown Position'. Suggest running 'poe consume' in your terminal to extract details, or toggle Mock Demo Data on the bottom-left.");
        setUseMockData(true); // Auto-enable mock data to prevent interface from showing all Unknown
      } else {
        setUseMockData(false); // Normal case: use real database
      }
    } catch (err: any) {
      console.warn("Failed to fetch jobs from backend server:", err.message);
      setApiStatus("offline");
      setUseMockData(true); // Force mock data when offline
      setErrorMsg("No local FastAPI backend service detected. Enabled Mock Demo Data automatically.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);



  // Determine dataset to render
  const currentJobsSource = useMemo(() => {
    return useMockData ? MOCK_JOBS : jobs;
  }, [useMockData, jobs, MOCK_JOBS]);

  // Dynamically extract filter options from current data source
  const companyOptions = useMemo(() => {
    const names = currentJobsSource.map(j => j.company_name);
    return Array.from(new Set(names)).filter(Boolean);
  }, [currentJobsSource]);

  const locationOptions = useMemo(() => {
    const locs = currentJobsSource.map(j => j.location);
    return Array.from(new Set(locs)).filter(Boolean);
  }, [currentJobsSource]);

  const filteredJobs = useMemo(() => {
    if (isAiMode) {
      return aiJobs;
    }
    return currentJobsSource.filter(job => {
      // 1. Keyword filter
      const matchesSearch = searchQuery === "" || 
        job.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        job.company_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (job.department && job.department.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (job.location && job.location.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (job.description && job.description.toLowerCase().includes(searchQuery.toLowerCase()));

      // 2. Company filter
      const matchesCompany = selectedCompanies.length === 0 || 
        selectedCompanies.includes(job.company_name);

      // 3. Location filter
      const matchesLocation = selectedLocation === "all" || 
        job.location === selectedLocation;

      // 4. Status filter
      const matchesStatus = selectedStatus === "all" || 
        job.status.toLowerCase() === selectedStatus.toLowerCase();

      return matchesSearch && matchesCompany && matchesLocation && matchesStatus;
    });
  }, [currentJobsSource, searchQuery, selectedCompanies, selectedLocation, selectedStatus, isAiMode, aiJobs]);

  // Dynamically count matching jobs per company under other filters
  const companyCounts = useMemo<Record<string, number>>(() => {
    const counts: Record<string, number> = {};
    companyOptions.forEach(c => { counts[c] = 0; });
    
    currentJobsSource.forEach(job => {
      const matchesSearch = searchQuery === "" || 
        job.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        job.company_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (job.department && job.department.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (job.location && job.location.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (job.description && job.description.toLowerCase().includes(searchQuery.toLowerCase()));

      const matchesLocation = selectedLocation === "all" || job.location === selectedLocation;
      const matchesStatus = selectedStatus === "all" || job.status.toLowerCase() === selectedStatus.toLowerCase();

      if (matchesSearch && matchesLocation && matchesStatus) {
        if (counts[job.company_name] !== undefined) {
          counts[job.company_name]++;
        }
      }
    });
    return counts;
  }, [currentJobsSource, companyOptions, searchQuery, selectedLocation, selectedStatus]);

  // Dynamically count matching jobs per location under other filters
  const locationCounts = useMemo<Record<string, number>>(() => {
    const counts: Record<string, number> = {};
    locationOptions.forEach(l => { counts[l] = 0; });
    let totalMatchingAll = 0;
    
    currentJobsSource.forEach(job => {
      const matchesSearch = searchQuery === "" || 
        job.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        job.company_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (job.department && job.department.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (job.location && job.location.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (job.description && job.description.toLowerCase().includes(searchQuery.toLowerCase()));

      const matchesCompany = selectedCompanies.length === 0 || selectedCompanies.includes(job.company_name);
      const matchesStatus = selectedStatus === "all" || job.status.toLowerCase() === selectedStatus.toLowerCase();

      if (matchesSearch && matchesCompany && matchesStatus) {
        totalMatchingAll++;
        if (counts[job.location] !== undefined) {
          counts[job.location]++;
        }
      }
    });
    return { ...counts, all: totalMatchingAll };
  }, [currentJobsSource, locationOptions, searchQuery, selectedCompanies, selectedStatus]);

  // Dynamically count matching jobs per status under other filters
  const statusCounts = useMemo<Record<string, number>>(() => {
    const counts: Record<string, number> = { active: 0, closed: 0 };
    let totalMatchingAll = 0;

    currentJobsSource.forEach(job => {
      const matchesSearch = searchQuery === "" || 
        job.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        job.company_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (job.department && job.department.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (job.location && job.location.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (job.description && job.description.toLowerCase().includes(searchQuery.toLowerCase()));

      const matchesCompany = selectedCompanies.length === 0 || selectedCompanies.includes(job.company_name);
      const matchesLocation = selectedLocation === "all" || job.location === selectedLocation;

      if (matchesSearch && matchesCompany && matchesLocation) {
        totalMatchingAll++;
        const s = job.status.toLowerCase();
        if (counts[s] !== undefined) {
          counts[s]++;
        }
      }
    });
    return { ...counts, all: totalMatchingAll };
  }, [currentJobsSource, searchQuery, selectedCompanies, selectedLocation]);

  // Reset location/status filter to "all" if their matching count drops to 0
  useEffect(() => {
    if (selectedLocation !== "all" && locationCounts && (locationCounts[selectedLocation] || 0) === 0) {
      setSelectedLocation("all");
    }
  }, [selectedLocation, locationCounts]);

  useEffect(() => {
    if (selectedStatus !== "all" && statusCounts && (statusCounts[selectedStatus] || 0) === 0) {
      setSelectedStatus("all");
    }
  }, [selectedStatus, statusCounts]);

  // Get selected or default job
  const selectedJob = useMemo(() => {
    if (selectedJobId === null) {
      // If none selected, default to the first one
      return filteredJobs.length > 0 ? filteredJobs[0] : null;
    }
    const found = filteredJobs.find(j => j.id === selectedJobId);
    // Fallback to first if previously selected job is no longer available
    return found || (filteredJobs.length > 0 ? filteredJobs[0] : null);
  }, [selectedJobId, filteredJobs]);

  // Simple Markdown parser to render job description
  const parseMarkdown = (text: string | null) => {
    if (!text) return <p>No detailed job description available.</p>;
    
    const lines = text.split("\n");
    let inList = false;
    let listItems: string[] = [];
    const elements: React.ReactNode[] = [];
    
    lines.forEach((line, index) => {
      const trimmed = line.trim();
      
      // Match H3 header (### Title)
      if (trimmed.startsWith("###")) {
        if (inList) {
          elements.push(
            <ul key={`list-${index}`}>
              {listItems.map((item, i) => <li key={i}>{item}</li>)}
            </ul>
          );
          inList = false;
          listItems = [];
        }
        elements.push(<h3 key={`h3-${index}`}>{trimmed.replace("###", "").trim()}</h3>);
      } 
      // Match unordered list (- item or * item)
      else if (trimmed.startsWith("-") || trimmed.startsWith("*")) {
        inList = true;
        listItems.push(trimmed.substring(1).trim());
      } 
      // Empty line
      else if (trimmed === "") {
        if (inList) {
          elements.push(
            <ul key={`list-${index}`}>
              {listItems.map((item, i) => <li key={i}>{item}</li>)}
            </ul>
          );
          inList = false;
          listItems = [];
        }
      } 
      // Normal text paragraph
      else {
        if (inList) {
          elements.push(
            <ul key={`list-${index}`}>
              {listItems.map((item, i) => <li key={i}>{item}</li>)}
            </ul>
          );
          inList = false;
          listItems = [];
        }
        elements.push(<p key={`p-${index}`}>{trimmed}</p>);
      }
    });

    if (inList && listItems.length > 0) {
      elements.push(
        <ul key="list-end">
          {listItems.map((item, i) => <li key={i}>{item}</li>)}
        </ul>
      );
    }
    
    return <div className="description-content">{elements}</div>;
  };

  // Format timestamp
  const formatDate = (isoStr: string | null) => {
    if (!isoStr) return "N/A";
    try {
      const date = new Date(isoStr);
      return date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit"
      });
    } catch {
      return isoStr;
    }
  };

  const handleCompanyToggle = (company: string) => {
    setSelectedCompanies(prev => 
      prev.includes(company)
        ? prev.filter(c => c !== company)
        : [...prev, company]
    );
  };

  return (
    <div className="app-container">
      {/* 1. Left Sidebar: Filter Control Panel */}
      <aside className="glass-panel sidebar">
        <h1 className="sidebar-title">
          <Briefcase strokeWidth={2.5} size={24} style={{ color: "#818cf8" }} />
          JobSeeker Hub
        </h1>

        {/* AI Resume Matching */}
        <div className="ai-section">
          <div className="ai-title">
            <Sparkles size={16} style={{ color: "#c084fc" }} />
            AI Resume Matching
          </div>
          
          {!isAiMode ? (
            <>
              <textarea
                className="ai-textarea"
                placeholder="Paste your resume text here. The LLM will automatically analyze and match the most suitable roles for you..."
                value={resumeText}
                onChange={(e) => {
                  setResumeText(e.target.value);
                  setSelectedFileName(null);
                }}
              />
              
              <div 
                className="ai-upload-zone"
                onClick={() => document.getElementById("resume-file-input")?.click()}
              >
                <UploadCloud size={20} style={{ color: "var(--text-muted)", margin: "0 auto" }} />
                <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-secondary)", marginTop: "8px" }}>
                  {selectedFileName ? `Selected: ${selectedFileName}` : "Upload Resume File"}
                </div>
                <div className="ai-upload-text">Supports .pdf, .txt, .md formats</div>
                <input 
                  type="file" 
                  id="resume-file-input" 
                  style={{ display: "none" }} 
                  accept=".pdf,.txt,.md"
                  onChange={handleFileUpload}
                />
              </div>
              
              <button 
                className="btn-ai-match" 
                onClick={handleAiMatch}
                style={{ width: "100%" }}
              >
                <Sparkles size={14} /> Start Smart Matching
              </button>
            </>
          ) : (
            <div>
              <div style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "12px", display: "flex", alignItems: "center", gap: "6px" }}>
                <CheckCircle size={14} style={{ color: "var(--success)" }} />
                Top matching positions recommended for you
              </div>
              <div className="ai-btn-group">
                <button 
                  className="btn-ai-clear"
                  onClick={() => {
                    setIsAiMode(false);
                    setResumeText("");
                    setSelectedFileName(null);
                    (window as any)._uploadedFile = null;
                  }}
                  style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}
                >
                  <X size={14} /> Clear Recommendation
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Keyword Search */}
        <div className="sidebar-section">
          <div className="section-label">
            <Search size={14} /> Search Jobs
          </div>
          <div className="search-wrapper">
            <Search className="search-icon" />
            <input 
              type="text" 
              className="search-input" 
              placeholder="Keywords, skills, or company..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        {/* Company Filter (Multi-select) */}
        <div className="sidebar-section">
          <div className="section-label">
            <Building size={14} /> Companies
          </div>
          <div className="filter-list">
            {companyOptions.map(company => (
              <div 
                key={company} 
                className={`filter-item ${selectedCompanies.includes(company) ? 'active' : ''}`}
                onClick={() => handleCompanyToggle(company)}
              >
                <div className="filter-checkbox">
                  {selectedCompanies.includes(company) && "✓"}
                </div>
                <span className="filter-label">{company}</span>
                <span style={{ 
                  marginLeft: "auto", 
                  fontSize: "11px", 
                  color: selectedCompanies.includes(company) ? "rgba(255,255,255,0.85)" : "var(--text-muted)",
                  background: selectedCompanies.includes(company) ? "rgba(255,255,255,0.18)" : "rgba(255,255,255,0.04)",
                  padding: "2px 6px",
                  borderRadius: "4px",
                  fontWeight: 600
                }}>
                  {companyCounts[company] || 0}
                </span>
              </div>
            ))}
            {companyOptions.length === 0 && (
              <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>No companies available</span>
            )}
          </div>
        </div>

        {/* Location Filter (Select dropdown) */}
        <div className="sidebar-section">
          <div className="section-label">
            <MapPin size={14} /> Location
          </div>
          <div className="search-wrapper" style={{ marginBottom: 0 }}>
            <select 
              className="search-input"
              style={{ paddingLeft: "16px", appearance: "none", cursor: "pointer" }}
              value={selectedLocation}
              onChange={(e) => setSelectedLocation(e.target.value)}
            >
              <option value="all">All Locations ({locationCounts.all})</option>
              {locationOptions
                .filter(loc => (locationCounts[loc] || 0) > 0)
                .map(loc => (
                  <option key={loc} value={loc}>
                    {loc} ({locationCounts[loc] || 0})
                  </option>
                ))}
            </select>
            <ChevronDown size={16} style={{ position: "absolute", right: "14px", top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)", pointerEvents: "none" }} />
          </div>
        </div>

        {/* Status Filter */}
        <div className="sidebar-section" style={{ marginBottom: "32px" }}>
          <div className="section-label">
            <Clock size={14} /> Job Status
          </div>
          <div className="search-wrapper" style={{ marginBottom: 0 }}>
            <select 
              className="search-input"
              style={{ paddingLeft: "16px", appearance: "none", cursor: "pointer" }}
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value)}
            >
              <option value="all">All Statuses ({statusCounts.all})</option>
              {(statusCounts.active || 0) > 0 && (
                <option value="active">Active ({statusCounts.active})</option>
              )}
              {(statusCounts.closed || 0) > 0 && (
                <option value="closed">Closed ({statusCounts.closed})</option>
              )}
            </select>
            <ChevronDown size={16} style={{ position: "absolute", right: "14px", top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)", pointerEvents: "none" }} />
          </div>
        </div>

        {/* Control Panel: API Status & Mock Toggle */}
        <div className="control-panel">
          <div className="status-row">
            <span style={{ color: "var(--text-secondary)", fontWeight: 600 }}>API Connectivity</span>
            <div className="status-indicator">
              <span className={`status-dot ${apiStatus === 'online' ? 'online' : apiStatus === 'offline' ? 'offline' : 'mocking'}`} />
              <span style={{ fontSize: "12px" }}>
                {apiStatus === "checking" && "Connecting..."}
                {apiStatus === "online" && "Service Connected"}
                {apiStatus === "offline" && "Service Offline"}
              </span>
            </div>
          </div>

          <div 
            className={`toggle-container ${useMockData ? 'active' : ''}`}
            onClick={() => {
              if (apiStatus !== "offline") {
                setUseMockData(!useMockData);
              }
            }}
            title={apiStatus === "offline" ? "Local backend service not found, forcing Mock Data" : "Switch between real local database and Mock demo data"}
            style={{ opacity: apiStatus === "offline" ? 0.7 : 1, cursor: apiStatus === "offline" ? "not-allowed" : "pointer" }}
          >
            <span style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: "6px" }}>
              <Database size={14} /> Enable Mock Demo Data
            </span>
            <div className="toggle-switch" />
          </div>

          <button 
            onClick={fetchData} 
            className="btn-primary" 
            style={{ 
              marginTop: "8px", 
              width: "100%", 
              justifyContent: "center", 
              padding: "8px",
              background: "rgba(255,255,255,0.06)",
              border: "1px solid var(--glass-border)",
              boxShadow: "none"
            }}
          >
            <RefreshCw size={13} className={loading ? "spin" : ""} style={{ animation: loading ? "float 1.5s linear infinite" : "none" }} />
            Refresh Data
          </button>
        </div>
      </aside>

      {/* 2. Middle Column: Job Cards List */}
      <section className="glass-panel list-container">
        <div className="list-header">
          <h2 className="list-title">Job Postings</h2>
          <p className="list-subtitle">
            {useMockData ? "Showing Demo Data" : "Connected to Local Database"} • {filteredJobs.length} results
          </p>
        </div>

        {/* Top warning banner */}
        {errorMsg && (
          <div style={{
            margin: "16px 16px 0 16px",
            padding: "12px",
            background: "rgba(239, 68, 68, 0.1)",
            border: "1px solid rgba(239, 68, 68, 0.25)",
            borderRadius: "var(--radius-sm)",
            fontSize: "12px",
            color: "#fca5a5",
            display: "flex",
            alignItems: "flex-start",
            gap: "8px",
            lineHeight: 1.4
          }}>
            <AlertCircle size={16} style={{ flexShrink: 0, marginTop: "2px" }} />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Scrollable List */}
        <div className="jobs-scrollable">
          {loading && jobs.length === 0 ? (
            <div className="empty-state" style={{ height: "100%" }}>
              <RefreshCw className="spin" size={24} style={{ animation: "float 2s linear infinite" }} />
              <span style={{ fontSize: "13px" }}>Loading jobs data...</span>
            </div>
          ) : filteredJobs.map(job => (
            <article 
              key={job.id} 
              className={`job-card ${selectedJob?.id === job.id ? 'selected' : ''}`}
              onClick={() => setSelectedJobId(job.id)}
            >
              <div className="job-card-header">
                <h3 className="job-card-title">{job.title}</h3>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "6px", flexShrink: 0 }}>
                  <span className="company-badge">{job.company_name}</span>
                  {isAiMode && (job as any).match_score !== undefined && (
                    <span className={`match-score-badge ${
                      (job as any).match_score >= 90 ? 'high' : (job as any).match_score >= 80 ? 'medium' : 'low'
                    }`}>
                      {(job as any).match_score}% Match
                    </span>
                  )}
                </div>
              </div>

              <div className="job-card-meta">
                {job.department && (
                  <span className="meta-pill">
                    <Briefcase /> {job.department}
                  </span>
                )}
                <span className="meta-pill">
                  <MapPin /> {job.location}
                </span>
                {job.salary && (
                  <span className="meta-pill" style={{ color: "var(--success)" }}>
                    <DollarSign /> {job.salary}
                  </span>
                )}
              </div>

              <div className="job-card-footer">
                <span>Updated: {formatDate(job.last_seen_at)}</span>
                <span style={{ 
                  color: job.status.toLowerCase() === 'active' ? 'var(--success)' : 'var(--text-muted)',
                  fontWeight: 600,
                  textTransform: 'uppercase'
                }}>
                  {job.status}
                </span>
              </div>
            </article>
          ))}

          {filteredJobs.length === 0 && (
            <div className="empty-state">
              <HelpCircle size={36} style={{ color: "var(--text-muted)" }} />
              <p style={{ fontSize: "14px", fontWeight: 500 }}>No matching jobs found</p>
              <p style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "-8px" }}>Try adjusting filters or keywords</p>
            </div>
          )}
        </div>
      </section>

      {/* 3. Right Sidebar: Job Detail Panel */}
      <main className="detail-container">
        {selectedJob ? (
          <>
            {/* Detail Header */}
            <div className="detail-header">
              <h2 className="detail-title">{selectedJob.title}</h2>
              <div className="detail-company-row">
                <span className="detail-company-name">{selectedJob.company_name}</span>
                {selectedJob.department && (
                  <span className="company-badge" style={{ background: "rgba(99, 102, 241, 0.15)", borderColor: "var(--accent)", color: "#c7d2fe" }}>
                    {selectedJob.department}
                  </span>
                )}
                <a 
                  href={selectedJob.job_url} 
                  target="_blank" 
                  rel="noreferrer" 
                  className="btn-primary" 
                  style={{ marginLeft: "auto", padding: "6px 14px", fontSize: "12px" }}
                >
                  Apply <ExternalLink size={12} />
                </a>
              </div>
            </div>

            {/* AI Recommendation Analysis Card */}
            {isAiMode && (selectedJob as any).match_score !== undefined && (
              <div className="ai-recommendation-card">
                <div className="ai-rec-header">
                  <div className="ai-rec-title">
                    <Sparkles size={18} style={{ color: "#c084fc", marginRight: "6px" }} />
                    AI Match Recommendation Analysis
                  </div>
                  <div className="ai-rec-score-wrapper">
                    <div style={{ textAlign: "right" }}>
                      <span className="ai-rec-score-num">{(selectedJob as any).match_score}</span>
                      <span className="ai-rec-score-label">% Match Score</span>
                    </div>
                  </div>
                </div>
                <div className="ai-rec-reason">
                  {(selectedJob as any).match_reason}
                </div>
              </div>
            )}

            {/* Bento Grid Indicators */}
            <div className="bento-grid">
              <div className="bento-card">
                <div className="bento-icon">
                  <DollarSign size={18} />
                </div>
                <div className="bento-info">
                  <span className="bento-label">Salary Range</span>
                  <span className="bento-value" style={{ color: selectedJob.salary ? "var(--success)" : "var(--text-muted)" }}>
                    {selectedJob.salary || "Not Disclosed / Negotiable"}
                  </span>
                </div>
              </div>

              <div className="bento-card">
                <div className="bento-icon">
                  <MapPin size={18} />
                </div>
                <div className="bento-info">
                  <span className="bento-label">Location</span>
                  <span className="bento-value">{selectedJob.location || "Unknown Location"}</span>
                </div>
              </div>

              <div className="bento-card">
                <div className="bento-icon">
                  <CheckCircle size={18} style={{ color: selectedJob.status.toLowerCase() === 'active' ? 'var(--success)' : 'var(--danger)' }} />
                </div>
                <div className="bento-info">
                  <span className="bento-label">Status</span>
                  <span className="bento-value" style={{ textTransform: "uppercase" }}>{selectedJob.status}</span>
                </div>
              </div>

              <div className="bento-card">
                <div className="bento-icon">
                  <Clock size={18} />
                </div>
                <div className="bento-info">
                  <span className="bento-label">First Crawled</span>
                  <span className="bento-value">{formatDate(selectedJob.first_seen_at)}</span>
                </div>
              </div>
            </div>

            {/* Job Description Body */}
            <div className="detail-body">
              <h3 className="description-title">Job Description & Requirements</h3>
              {parseMarkdown(selectedJob.description)}
            </div>

            {/* Raw JSON metadata (Collapsible) */}
            <div className="metadata-section">
              <div 
                className="metadata-header"
                onClick={() => setMetadataExpanded(!metadataExpanded)}
              >
                <span className="metadata-title">
                  <Database size={13} style={{ color: "var(--accent)" }} /> 
                  Raw Metadata Collected by Crawler
                </span>
                {metadataExpanded ? <ChevronUp size={16} style={{ color: "var(--text-muted)" }} /> : <ChevronDown size={16} style={{ color: "var(--text-muted)" }} />}
              </div>
              
              {metadataExpanded && (
                <pre className="metadata-content">
                  {JSON.stringify(selectedJob.raw_metadata || { message: "No raw metadata available for this job posting" }, null, 2)}
                </pre>
              )}
            </div>
          </>
        ) : (
          <div className="empty-state">
            <div className="empty-logo-glow">
              <Briefcase size={36} />
            </div>
            <h2 style={{ fontFamily: "var(--font-display)", fontSize: "20px", fontWeight: 700, color: "#fff", marginTop: "12px" }}>
              Select a job to view details
            </h2>
            <p style={{ fontSize: "13px", color: "var(--text-muted)", maxWidth: "300px" }}>
              Click on a job card in the left list to preview the full job description, salary range, and raw metadata.
            </p>
          </div>
        )}
      </main>
      {/* AI Matching Loader Overlay */}
      {aiMatching && (
        <div className="ai-loading-overlay">
          <div className="ai-loading-glow">
            <Sparkles size={36} style={{ color: "#c084fc" }} />
          </div>
          <div className="ai-loading-text-container">
            <div className="ai-loading-status">{aiLoadingStep}</div>
            <div className="ai-loading-subtext">The LLM is performing a two-stage evaluation over 800+ jobs in the database, please wait...</div>
          </div>
        </div>
      )}
    </div>
  );
}
