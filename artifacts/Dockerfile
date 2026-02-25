# ============================================
# Quacky Policy Summarizer — Docker Image
# Multi-stage build: ABC solver + Python app
# ============================================

# --- Stage 1: Build ABC and dependencies from source ---
FROM ubuntu:22.04 AS abc-builder

ENV DEBIAN_FRONTEND=noninteractive

# System deps for building ABC, Glog, and Mona
RUN apt-get update && apt-get install -y \
    git g++ cmake make \
    build-essential autoconf automake libtool intltool \
    flex bison python3 \
    && rm -rf /var/lib/apt/lists/*

# Build Glog
RUN git clone --depth 1 https://github.com/google/glog.git /tmp/glog \
    && cd /tmp/glog \
    && cmake -S . -B build -G "Unix Makefiles" \
    && cmake --build build \
    && cmake --build build --target install \
    && ldconfig

# Build Mona (with ABC patch)
RUN git clone --recursive https://github.com/vlab-cs-ucsb/ABC.git /opt/ABC
RUN git clone https://github.com/cs-au-dk/MONA.git /tmp/MONA \
    && cd /tmp/MONA \
    && git apply /opt/ABC/external/mona/mona_abc.patch \
    && libtoolize && aclocal && automake --gnu --add-missing && autoreconf -ivf \
    && ./configure && make all && make install && ldconfig

# Build ABC
RUN cd /opt/ABC \
    && ./autogen.sh \
    && ./configure \
    && make all \
    && make install \
    && ldconfig

# --- Stage 2: Runtime image ---
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install minimal runtime libs needed by ABC
RUN apt-get update && apt-get install -y \
    libstdc++6 libgcc-s1 \
    && rm -rf /var/lib/apt/lists/*

# Copy ABC binary and all shared libraries from builder
COPY --from=abc-builder /usr/local/bin/abc /usr/local/bin/abc
COPY --from=abc-builder /usr/local/lib/libabc.so* /usr/local/lib/
COPY --from=abc-builder /usr/local/lib/libglog.so* /usr/local/lib/
COPY --from=abc-builder /usr/local/lib/libmonadfa.so* /usr/local/lib/
COPY --from=abc-builder /usr/local/lib/libmonabdd.so* /usr/local/lib/
COPY --from=abc-builder /usr/local/lib/libmonamem.so* /usr/local/lib/
RUN ldconfig

# Set up working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
       fastapi==0.129.0 \
       uvicorn==0.41.0 \
       anthropic==0.82.0 \
       python-dotenv==1.2.1

# Copy application code
COPY src/ ./src/
COPY web/ ./web/
COPY samples/ ./samples/

# Expose port
EXPOSE 8000

# Provide the Anthropic API key at runtime:
#   docker run -e ANTHROPIC_API_KEY=sk-... -p 8000:8000 quacky
# Or via an env file:
#   docker run --env-file .env -p 8000:8000 quacky

CMD ["python", "web/app.py"]
