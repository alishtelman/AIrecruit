FROM golang:1.23-alpine AS builder

WORKDIR /src
COPY go.mod ./
COPY . .
RUN go build -o /out/api-gateway ./cmd/api-gateway

FROM alpine:3.20

WORKDIR /app
COPY --from=builder /out/api-gateway /app/api-gateway

EXPOSE 8080
CMD ["/app/api-gateway"]
