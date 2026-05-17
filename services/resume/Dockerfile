FROM golang:1.23-alpine AS builder

WORKDIR /src
COPY go.mod ./
COPY . .
RUN go build -o /out/resume-service ./cmd/resume-service

FROM alpine:3.20

WORKDIR /app
COPY --from=builder /out/resume-service /app/resume-service

ENV RESUME_SERVICE_ADDR=:8080
ENV RESUME_STORAGE_DIR=/app/storage/resumes

CMD ["/app/resume-service"]
