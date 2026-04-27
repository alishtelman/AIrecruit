FROM golang:1.23-alpine AS builder

WORKDIR /src
COPY go.mod ./
COPY . .
RUN go build -o /out/report-worker ./cmd/report-worker

FROM alpine:3.20

WORKDIR /app
COPY --from=builder /out/report-worker /app/report-worker

EXPOSE 8080
CMD ["/app/report-worker"]
