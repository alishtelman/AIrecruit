FROM golang:1.23-alpine AS builder

WORKDIR /src
COPY go.mod ./
COPY . .
RUN go build -o /out/llm-service ./cmd/llm-service

FROM alpine:3.20

WORKDIR /app
COPY --from=builder /out/llm-service /app/llm-service

EXPOSE 8080
CMD ["/app/llm-service"]
