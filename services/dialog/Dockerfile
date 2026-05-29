FROM golang:1.23-alpine AS builder

WORKDIR /src

# Copy db module and dialog module
COPY services/db /src/services/db
COPY services/dialog /src/services/dialog

# Run build from dialog folder
WORKDIR /src/services/dialog
RUN go mod tidy
RUN go build -o /out/dialog-service ./cmd/dialog-service

FROM alpine:3.20

WORKDIR /app
COPY --from=builder /out/dialog-service /app/dialog-service

EXPOSE 8080
CMD ["/app/dialog-service"]
