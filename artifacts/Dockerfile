# Multi-stage build for Quacky Pipeline Demo
FROM python:3.10-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    curl \
    cmake \
    autoconf \
    automake \
    libtool \
    intltool \
    pkg-config \
    bison \
    flex \
    libreadline-dev \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Semi-automated setup per UCSB ABC INSTALL.md
# 1) Clone ABC first to access MONA patch file
WORKDIR /tmp
RUN git clone --depth 1 --branch master https://github.com/vlab-cs-ucsb/ABC.git

# 2) Build and install Glog (dependency)
RUN git clone --depth 1 https://github.com/google/glog.git && \
    cd glog && \
    cmake -S . -B build -G "Unix Makefiles" && \
    cmake --build build -j"$(nproc)" && \
    cmake --install build

# 3) Build and install MONA with ABC patch
RUN git clone --depth 1 https://github.com/cs-au-dk/MONA.git && \
    cd MONA && \
    git apply /tmp/ABC/external/mona/mona_abc.patch && \
    libtoolize && aclocal && automake --gnu --add-missing && autoreconf -ivf && \
    ./configure && \
    make -j"$(nproc)" all && \
    make install && \
    ldconfig

# 4) Build and install ABC via autotools
RUN cd /tmp/ABC && \
    libtoolize && aclocal && automake --gnu --add-missing && autoreconf -ivf && \
    ./configure && \
    make -j1 && \
    make install

# Final stage
FROM python:3.10-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libgomp1 \
    curl \
    git \
    python3-pip \
    libreadline8 \
    && rm -rf /var/lib/apt/lists/*

# Copy ABC solver from builder
COPY --from=builder /usr/local/bin/abc /usr/local/bin/abc
COPY --from=builder /usr/local/lib/libabc* /usr/local/lib/
COPY --from=builder /usr/local/lib/libglog* /usr/local/lib/
COPY --from=builder /usr/local/lib/libmona* /usr/local/lib/
RUN ldconfig

# Set working directory for the app
WORKDIR /app

# Copy the modified quacky directory (with your customizations) to the expected location
RUN mkdir -p /opt/VerifyingLLMGeneratedPolicies/CPCA
COPY quacky /opt/VerifyingLLMGeneratedPolicies/CPCA/quacky

# Copy artifacts directory contents
COPY . /app/

# Install Python dependencies for Quacky
RUN pip install --no-cache-dir \
    cel-python \
    selenium \
    sentence-transformers \
    anthropic \
    openai \
    google-generativeai \
    scikit-learn \
    pandas \
    numpy \
    python-dotenv \
    streamlit \
    requests

# Install any additional requirements from requirements.txt if it exists
COPY requirements.txt* ./
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Create necessary directories
RUN mkdir -p /app/temp /app/results

# Create a wrapper script to set up environment
RUN echo '#!/bin/bash\n\
# Set up environment for Docker\n\
export QUACKY_PATH="/opt/VerifyingLLMGeneratedPolicies/CPCA/quacky/src/quacky.py"\n\
export QUACKY_DOCKER=1\n\
# Start the application\n\
exec streamlit run app.py --server.address=0.0.0.0 --server.port=8501 --server.headless=true --browser.gatherUsageStats=false' > /app/start.sh && \
    chmod +x /app/start.sh

# Expose Streamlit port
EXPOSE 8501

# Health check
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV QUACKY_DOCKER=1
ENV QUACKY_PATH=/opt/VerifyingLLMGeneratedPolicies/CPCA/quacky/src/quacky.py

# Run the application
CMD ["/app/start.sh"]